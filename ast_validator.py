import ast
import os
import sys

def get_python_files(directory):
    py_files = []
    for root, _, files in os.walk(directory):
        if '.agent' in root or 'venv' in root or '.venv' in root or '.git' in root or '__pycache__' in root:
            continue
        for file in files:
            if file.endswith('.py'):
                py_files.append(os.path.join(root, file))
    return py_files

def extract_function_signatures(files):
    signatures = {}
    for file in files:
        with open(file, 'r', encoding='utf-8') as f:
            try:
                tree = ast.parse(f.read(), filename=file)
            except SyntaxError as e:
                print(f"[{file}] SyntaxError: {e}")
                continue
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    # We only care about positional arguments for this basic check
                    args = [arg.arg for arg in node.args.args if arg.arg != 'self']
                    defaults = len(node.args.defaults)
                    min_args = len(args) - defaults
                    has_varargs = getattr(node.args, 'vararg', None) is not None
                    has_kwargs = getattr(node.args, 'kwarg', None) is not None
                    signatures[node.name] = {
                        'min_args': min_args,
                        'max_args': float('inf') if has_varargs else len(args),
                        'args': args,
                        'file': file,
                        'has_kwargs': has_kwargs
                    }
    return signatures

def validate_function_calls(files, signatures, result_file):
    issues_found = 0
    with open(result_file, 'w', encoding='utf-8') as out:
        for file in files:
            with open(file, 'r', encoding='utf-8') as f:
                try:
                    tree = ast.parse(f.read(), filename=file)
                except SyntaxError:
                    continue
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Name):
                            func_name = node.func.id
                        elif isinstance(node.func, ast.Attribute):
                            func_name = node.func.attr
                        else:
                            continue
                            
                        if func_name in signatures:
                            sig = signatures[func_name]
                            # Count positional args
                            num_pos_args = len(node.args)
                            # Count keyword args
                            # Identify provided names
                            provided_kw_names = [kw.arg for kw in node.keywords if kw.arg is not None]
                            
                            # Has kwargs expansion **kwargs
                            has_kwargs_expansion = any(kw.arg is None for kw in node.keywords)
                            # Has args expansion *args
                            has_args_expansion = any(isinstance(arg, ast.Starred) for arg in node.args)
                            
                            if has_kwargs_expansion or has_args_expansion:
                                continue # Too complex for simple static analysis
                                
                            missing_required = []
                            required_args = sig['args'][:sig['min_args']]
                            
                            satisfied_positional_names = sig['args'][:num_pos_args]
                            
                            for req_arg in required_args:
                                if req_arg not in satisfied_positional_names and req_arg not in provided_kw_names:
                                    missing_required.append(req_arg)
                                    
                            if missing_required:
                                out.write(f"❌ [Missing Argument] in {file}:{node.lineno}\n")
                                out.write(f"   Call to `{func_name}()` is missing required argument(s): {missing_required}\n")
                                out.write(f"   Signature expects minimum {sig['min_args']} (Total args: {sig['args']})\n")
                                issues_found += 1
                                
                            # Also check if too many arguments
                            if num_pos_args > sig['max_args']:
                                out.write(f"❌ [Too Many Arguments] in {file}:{node.lineno}\n")
                                out.write(f"   Call to `{func_name}()` provided {num_pos_args} positional args, but max is {sig['max_args']}\n")
                                issues_found += 1
                                
    return issues_found

def main():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__)))
    print(f"Scanning Python files in {root_dir}...")
    py_files = get_python_files(root_dir)
    print(f"Found {len(py_files)} files.")
    
    print("Extracting function signatures...")
    signatures = extract_function_signatures(py_files)
    print(f"Extracted {len(signatures)} signatures.")
    
    print("Validating function calls...")
    out_file = os.path.join(root_dir, 'ast_results.txt')
    issues = validate_function_calls(py_files, signatures, out_file)
    
    if issues == 0:
        print("✅ No missing argument issues found by AST validator!")
        sys.exit(0)
    else:
        print(f"⚠️ Found {issues} potential issues. Check ast_results.txt")
        sys.exit(1)

if __name__ == '__main__':
    main()
