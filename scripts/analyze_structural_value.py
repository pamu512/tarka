import ast
import os
import sys
import argparse
from pathlib import Path
from collections import defaultdict

def build_import_graph(base_dir: str):
    """
    Parses all Python files to figure out who imports whom.
    Returns a graph of inbound references.
    """
    inbound_refs = defaultdict(int)
    base_path = Path(base_dir).resolve()
    all_files = list(base_path.rglob("*.py"))
    
    # Exclude tests and scripts to focus on core infra
    target_files = [f for f in all_files if "tests" not in f.parts and "scripts" not in f.parts]
    
    # Track all known modules in our project
    project_modules = {str(f.with_suffix('').relative_to(base_path)).replace(os.sep, '.') for f in target_files}

    for file_path in target_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(file_path))
                
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in project_modules:
                            inbound_refs[alias.name] += 1
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        if node.module in project_modules:
                            inbound_refs[node.module] += 1
        except (SyntaxError, UnicodeDecodeError):
            continue 

    return project_modules, inbound_refs

def scan_for_stubs(file_path: Path) -> bool:
    """Returns True if the file contains lazy implementations (pass, ..., NotImplementedError)."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
            
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                for child in node.body:
                    if isinstance(child, ast.Pass):
                        return True
                    if isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant) and child.value.value is Ellipsis:
                        return True
                    if isinstance(child, ast.Raise) and isinstance(child.exc, ast.Name) and child.exc.id == "NotImplementedError":
                        return True
    except Exception:
        pass
    return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze structural value of Python modules.")
    parser.add_argument("target_dir", type=str, help="Directory to analyze")
    args = parser.parse_args()
    
    base_directory = args.target_dir
    
    if not os.path.exists(base_directory):
        print(f"Error: Directory '{base_directory}' does not exist.")
        sys.exit(1)
        
    print(f"--- INFRASTRUCTURE VALUE AUDIT: {base_directory} ---\n")
    
    modules, inbound_graph = build_import_graph(base_directory)
    candidates = []
    
    for mod in modules:
        # Ignore common entry points
        is_entry = any(mod.endswith(s) for s in ["main", "routes", "app", "__init__"])
        
        if inbound_graph[mod] == 0 and not is_entry:
            file_path = Path(base_directory) / (mod.replace('.', os.sep) + ".py")
            if file_path.exists():
                is_stub = scan_for_stubs(file_path)
                candidates.append((mod, is_stub))

    if not candidates:
        print("[CLEAN] No isolated modules found.")
    else:
        for mod, is_stub in sorted(candidates, key=lambda x: x[1], reverse=True):
            status = "[AUTO-DELETE]" if is_stub else "[MANUAL REVIEW]"
            print(f"{status:18} {mod}")
