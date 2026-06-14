import os
import subprocess
import tempfile

def execute_pyqgis_code(code: str) -> str:
    """
    Executes the provided PyQGIS code using the QGIS Python environment.
    The code should define a function named 'execute_task()'.
    """
    
    wrapper_code = f"""import sys
import os

from qgis.core import QgsApplication

# Set Prefix Path
qgis_prefix = os.environ.get('QGIS_PREFIX_PATH', r'C:\\Program Files\\QGIS 4.0.3\\apps\\qgis')
QgsApplication.setPrefixPath(qgis_prefix, True)
qgs = QgsApplication([], False)
qgs.initQgis()

try:
{chr(10).join('    ' + line for line in code.split(chr(10)))}
    
    print("=== QGIS EXECUTION START ===")
    if 'execute_task' in locals() or 'execute_task' in globals():
        execute_task()
    else:
        print("Error: No execute_task() function found in generated code.")
    print("=== QGIS EXECUTION END ===")
except Exception as e:
    import traceback
    print("=== QGIS EXECUTION ERROR ===")
    traceback.print_exc()
finally:
    qgs.exitQgis()
"""

    fd, temp_path = tempfile.mkstemp(suffix=".py", prefix="qgis_script_")
    os.close(fd)
    
    with open(temp_path, 'w', encoding='utf-8') as f:
        f.write(wrapper_code)

    qgis_python_bat = r"C:\Program Files\QGIS 4.0.3\bin\python-qgis.bat"
    if not os.path.exists(qgis_python_bat):
        return f"Error: QGIS executable not found at {qgis_python_bat}"

    try:
        # Use python-qgis.bat to execute the temporary script
        # Setting errors='replace' to avoid decode errors if QGIS outputs weird characters
        result = subprocess.run(
            [qgis_python_bat, temp_path],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        
        return f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"

    except Exception as e:
        return f"Subprocess failed: {str(e)}"
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

if __name__ == '__main__':
    # Test execution with a safe script
    test_code = '''
def execute_task():
    print("Hello from QGIS Executor!")
    from qgis.core import QgsProject
    print("QGIS Project instantiated:", QgsProject.instance())
'''
    print(execute_pyqgis_code(test_code))
