import argparse
import re

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def parse_memory(str):
  assert str.endswith('B')
  str = str[:-1]
  if str.endswith('K'):
    return float(str[:-1]) * 10**3
  elif str.endswith('M'):
    return float(str[:-1]) * 10**6
  elif str.endswith('G'):
    return float(str[:-1]) * 10**9
  else:
    return float(str)

def print_memory(num):
    num = float('{:.3g}'.format(num))
    magnitude = 0
    while abs(num) >= 1000 and magnitude < 2:
        magnitude += 1
        num /= 1000.0
    return '{}{}B'.format('{:f}'.format(num).rstrip('0').rstrip('.'), ['', 'K', 'M'][magnitude])


parser = argparse.ArgumentParser(description='Compute significant differences of two tfprof scope output files')
parser.add_argument('file0', help='First (left) file to compare')
parser.add_argument('file1', help='Second (right) file to compare')
parser.add_argument('name0', default='left', nargs='?', help='Name of first file')
parser.add_argument('name1', default='right', nargs='?', help='Name of second file')
parser.add_argument('--max_depth', default=-1, nargs='?', type=int, help='Maximum shown depth of output tree (default: -1 = disabled)')
parser.add_argument('--delta', default=0.1, nargs='?', type=float, help='Minimum relative difference between individual scopes memories for node to be shown (default: 0.1 = 10%%)')
parser.add_argument('--min_size', default='1MB', nargs='?', type=parse_memory, help='Minimum absolute memory value for node to be shown (default: 1MB)')
parser.add_argument('--swap_files', dest='negative_data_diff', action='store_const', const=True, default=False, help='Calculate memory difference between file 1 and file 0 (default: between file 0 and 1)')
parser.add_argument('--hide_nodes', default=[], nargs='*', help='Do not show children of nodes with these paths, matched by given list of regexps')
parser.add_argument('--extra_files', default=[], nargs='*', help='Extra files to compare when comparing more than two')
parser.add_argument('--extra_names', default=[], nargs='*', help='Extra file names when comparing more than two files')

args = parser.parse_args()

max_depth, delta, min_size = args.max_depth, args.delta, args.min_size
hide_nodes_patterns = [re.compile('^%s$' % path) for path in args.hide_nodes]

assert len(args.extra_names) == len(args.extra_files), 'Supply exactly one extra scope name (via --scope_names) for every extra scope file'
scope_names = [args.name0, args.name1] + args.extra_names
scope_files = [args.file0, args.file1] + args.extra_files

scope_datas = [open(file_name).readlines() for file_name in scope_files]

diff_from, diff_to = scope_names[-1], scope_names[0]
if args.negative_data_diff:
  diff_from, diff_to = diff_to, diff_from

class ScopeNode:
  def __init__(self, name, full_path):
    self.name = name
    self.full_path = full_path
    self.children = dict()
    self.data = dict()

  def get_or_make_child(self, child_name):
    if not child_name in self.children:
      child = ScopeNode(child_name, self.full_path + [child_name])
      self.children[child_name] = child
      return child
    else:
      return self.children[child_name]

  def data_diff(self):
    return self.data.get(diff_to, 0) - self.data.get(diff_from, 0)

  def data_relative(self):
    try:
      return self.data.get(diff_to, 0) / self.data.get(diff_from, 0)
    except ZeroDivisionError:
      return float('Inf')

root = ScopeNode('_TFProfRoot', [])

for scope_name, scope_data in zip(scope_names, scope_datas):
  saw_root = False
  for line in scope_data:
    line = line.strip()
    if line.startswith('_TFProfRoot'):
      saw_root = True
    if not saw_root:
      continue
    split = line.split()
    assert len(split) == 2
    full_path_str, data_str = split
    full_path = full_path_str.split('/')
    assert data_str.startswith('(') and data_str.endswith(')')
    data_str = data_str[1:-1]
    data_list = data_str.split('/')
    data = parse_memory(data_list[-1])

    # add node to graph
    node = root
    if not full_path_str == '_TFProfRoot':
      for next in full_path:
        node = node.get_or_make_child(next)
    node.data[scope_name] = data


# find nodes with large differences
def is_significant(node, delta=0.1, min_size=1 * 10**6):
  if not node.data or max(node.data.values()) >= min_size:
    if any(scope_name not in node.data for scope_name in scope_names):
      return True
    elif max(node.data.values()) > min(node.data.values()) * (1+delta):
      return True

  return any(is_significant(child, delta=delta, min_size=min_size) for child in node.children.values())

def analyse_node(node, delta=0.1, min_size=1 * 10**6, max_depth=-1):
  if not is_significant(node, delta=delta, min_size=min_size):
    return
  if max_depth > 0 and len(node.full_path) > max_depth:
    return

  prefix = '  ' * len(node.full_path) + '/'.join(node.full_path)
  if len(node.full_path) == 0:
    prefix = '_TfProfRoot'
  data_str = ' '.join([scope_name + ':' + print_memory(data) for scope_name, data in sorted(node.data.items(), key=lambda n: scope_names.index(n[0]))])
  diff_str = print_memory(node.data_diff())
  rel_diff_str = ('x%.1f' % node.data_relative()) if not node.data_relative() == float('inf') else ''
  if not diff_str[0] == '-':
    diff_str = '+' + diff_str
  color = bcolors.WARNING if node.data_diff() > 0 else bcolors.OKBLUE

  print(prefix, '(%s) %s%s %s%s' % (data_str, color, diff_str, rel_diff_str, bcolors.ENDC))

  if not any(pattern.match('/'.join(node.full_path)) for pattern in hide_nodes_patterns):
    for child_node in sorted(node.children.values(), key=lambda node: node.data_diff(), reverse=True):
      analyse_node(child_node, delta=delta, min_size=min_size, max_depth=max_depth)

print('Comparing scope files %s' % ', '.join(['%s (%s)' % scope for scope in zip(scope_files, scope_names)]))
print(' - Showing nodes with minimum size >= %s and relative difference in memory >= %s or such children' % (print_memory(min_size), str(delta * 100) + '%'))
print(' - Showing absolute memory differences memory(%s) - memory(%s) and relative memory differences memory(%s) / memory(%s)' % (diff_to, diff_from, diff_to, diff_from))
if max_depth > 0:
  print(' - Showing nodes up to depth %s' % max_depth)
print()
analyse_node(root, delta=delta, min_size=min_size, max_depth=max_depth)
