import json
import os


with open(os.getcwd() + '/pods.json', 'r') as jfile:
    lines = jfile.readlines()

pods_lines = []
for l in lines:
    wl = l
    if l == '}\n':
        wl = '},\n'
    pods_lines.append(wl)

for line in [-1,-2,-3,-4]:
    if pods_lines[line] == "},\n":
        pods_lines[line] = "}\n"
        break

pods_lines = ['{\"pods\":\n', '[\n'] + pods_lines + [']\n', '}\n']
with open('/tmp/temp_pods.json', 'w') as output_file:
    output_file.writelines(pods_lines)

with open('/tmp/temp_pods.json', 'r') as tmp_file:
    pods_data = json.load(tmp_file)
pods = pods_data["pods"]

with open(os.getcwd() + '/nodes.json', 'r') as jfile:
    lines = jfile.readlines()

nodes_lines = []
for l in lines:
    wl = l
    if l == '}\n':
        wl = '},\n'
    nodes_lines.append(wl)

for line in [-1,-2,-3,-4]:
    if nodes_lines[line] == "},\n":
        nodes_lines[line] = "}\n"
        break
nodes_lines = ['[\n'] + nodes_lines + [']\n']
with open('/tmp/temp_node.json', 'w') as output_file:
    output_file.writelines(nodes_lines)

with open('/tmp/temp_node.json', 'r') as tmp_file:
    nodes_data = json.load(tmp_file)

output = {"pods": pods, "nodes": nodes_data}

outpath = os.getcwd() + '/input_example.json'
with open(outpath, 'w') as outfile:
    json.dump(output, outfile)
print("saved to ", outpath)