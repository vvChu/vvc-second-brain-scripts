import os, json, re

logs_dir = r'C:\Users\chuvu\.gemini\antigravity\brain'
recovery_dir = r'd:\VvC_Notes\scripts_recovered'
os.makedirs(recovery_dir, exist_ok=True)

file_versions = {}

for root, _, files in os.walk(logs_dir):
    if 'overview.txt' in files:
        log_path = os.path.join(root, 'overview.txt')
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.startswith(':'): continue
                try:
                    data = json.loads(line[1:])
                    timestamp = data.get('created_at', '')
                    
                    if 'tool_calls' in data:
                        for call in data['tool_calls']:
                            name = call.get('name')
                            args = call.get('args', {})
                            
                            if name in ['write_to_file', 'replace_file_content', 'multi_replace_file_content']:
                                target = args.get('TargetFile', '')
                                if target: target = json.loads(target)
                                if target and target.endswith('.py') and 'scripts' in target:
                                    if name == 'write_to_file':
                                        content = json.loads(args.get('CodeContent', '""'))
                                        if target not in file_versions or file_versions[target]['time'] < timestamp:
                                            file_versions[target] = {'time': timestamp, 'content': content}
                                    # For replace tools, it's harder because it's a diff, so we'll just ignore for now unless needed.

                    if data.get('type') == 'TOOL_RESPONSE' or 'tool_responses' in data:
                        for resp in data.get('tool_responses', []):
                            if resp.get('name') == 'view_file':
                                output = resp.get('response', {}).get('output', '')
                                m = re.search(r'File Path: `file:///(.*?)`', output)
                                if m:
                                    target = m.group(1).replace('/', '\\')
                                    if '%' in target:
                                        from urllib.parse import unquote
                                        target = unquote(target)
                                    if target[1] == ':':
                                        target = target[0].lower() + target[1:]
                                    
                                    if target.endswith('.py') and 'scripts' in target:
                                        lines = output.split('\n')
                                        code_lines = []
                                        is_code = False
                                        for l in lines:
                                            if l.startswith('The following code has been modified'):
                                                is_code = True
                                                continue
                                            if l.startswith('The above content shows'):
                                                is_code = False
                                                continue
                                            if is_code:
                                                lm = re.match(r'^\d+:\s?(.*)', l)
                                                if lm:
                                                    code_lines.append(lm.group(1))
                                                else:
                                                    code_lines.append(l)
                                        
                                        content = '\n'.join(code_lines)
                                        if content.strip():
                                            if target not in file_versions or file_versions[target]['time'] < timestamp:
                                                file_versions[target] = {'time': timestamp, 'content': content}
                except Exception as e:
                    pass

for target, info in file_versions.items():
    print(f"Recovered {target} (Time: {info['time']})")
    out_path = os.path.join(recovery_dir, os.path.basename(target))
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(info['content'])

print(f"Total recovered: {len(file_versions)}")
