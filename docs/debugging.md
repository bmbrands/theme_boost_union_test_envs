# Debugging with VS Code

You can debug the Python tool directly from VS Code using the `debugpy` debugger. Two launch configurations are provided in `.vscode/launch.json`.

## Prerequisites

1. **VS Code** with the [Python extension](https://marketplace.visualstudio.com/items?itemName=ms-python.python) installed
2. **Conda environment active** — the launch config points to `/opt/homebrew/Caskroom/miniconda/base/envs/boost-union-envs/bin/python`
3. **`debugpy` installed** in the conda environment:
   ```bash
   conda activate boost-union-envs
   pip install debugpy
   ```

## Option 1: Launch from VS Code (Recommended)

The "Launch" configurations run a command directly from VS Code with the debugger attached. You can set breakpoints in any Python file and they will be hit immediately.

**Example — the `list` command:**

1. Open VS Code in the project root
2. Go to **Run and Debug** (`⌘⇧D` on macOS / `Ctrl+Shift+D`)
3. Select **"Launch: list"** from the dropdown
4. Press **F5** (or the green play button)
5. The `list` command runs and stops at any breakpoints you've set

The launch configuration runs the tool as a Python module (`-m theme_boost_union_test_envs`) with the specified arguments:

```json
{
    "name": "Launch: list",
    "type": "debugpy",
    "request": "launch",
    "python": "/opt/homebrew/Caskroom/miniconda/base/envs/boost-union-envs/bin/python",
    "module": "theme_boost_union_test_envs",
    "args": ["list"],
    "cwd": "${workspaceFolder}"
}
```

To debug a different command (e.g. `start my-infra 4.5.2`), duplicate the configuration and change the `args` array:

```json
{
    "name": "Launch: start my-infra",
    "type": "debugpy",
    "request": "launch",
    "python": "/opt/homebrew/Caskroom/miniconda/base/envs/boost-union-envs/bin/python",
    "module": "theme_boost_union_test_envs",
    "args": ["start", "my-infra", "4.5.2"],
    "cwd": "${workspaceFolder}"
}
```

## Option 2: Attach to a Running Process

Useful when you want to run the tool from the terminal (e.g. with specific shell environment) and attach the debugger after it starts waiting.

1. Start the tool with `debugpy` listening:
   ```bash
   conda activate boost-union-envs
   python -m debugpy --listen 5678 --wait-for-client -m theme_boost_union_test_envs list
   ```
   The process will **pause** and wait for the debugger to connect.

2. In VS Code, select **"Attach (vanuit terminal)"** and press **F5**
3. The debugger connects to `localhost:5678` and execution continues, hitting your breakpoints

## How It Works Under the Hood

The `./boost-union-envs` script is simply a thin wrapper:

```python
#!/usr/bin/env python
from theme_boost_union_test_envs import app
from theme_boost_union_test_envs.app import UserInterface

if __name__ == "__main__":
    sys.exit(app.main(UserInterface.CLI))
```

The VS Code launch config bypasses this script and runs the package directly via `python -m theme_boost_union_test_envs`, which invokes `__main__.py` → `cli.py` → `app.main(UserInterface.CLI)`. The end result is the same, but going through the module system allows `debugpy` to instrument the code properly.

## Tips

- **Set breakpoints** by clicking in the gutter (left of line numbers) in any `.py` file
- **Conditional breakpoints**: right-click a breakpoint → "Edit Breakpoint" → add a condition like `moodle_version == "5.1.0"`
- **Watch expressions**: add variables like `self.yaml_parser`, `infrastructure_name`, etc. to the Watch panel
- **Debug Console**: while paused at a breakpoint, use the Debug Console (`⌘⇧Y`) to evaluate Python expressions in the current scope
- The tool uses **dependency injection** (`dependency-injector`), so to inspect the DI container state, evaluate `Application()` in the Debug Console
