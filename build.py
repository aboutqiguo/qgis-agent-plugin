import os
import zipfile
import shutil

def build_plugin():
    # 配置选项
    plugin_dir = "qgis_agent_plugin"
    output_zip = "qgis_agent_plugin_v1.0.0.zip"
    
    # 需要严格排除的文件和文件夹
    exclude_dirs = {'__pycache__', '.git', 'test_data', 'tests', 'temp_images'}
    exclude_files = {'.env', '.gitignore', 'build.py'}
    exclude_exts = {'.pyc', '.pyo'}

    if not os.path.exists(plugin_dir):
        print(f"Error: Directory '{plugin_dir}' not found.")
        return

    # 创建 zip 文件
    print(f"Building {output_zip} ...")
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(plugin_dir):
            # 过滤掉不需要的目录
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                # 过滤掉不需要的文件和后缀
                if file in exclude_files:
                    continue
                if any(file.endswith(ext) for ext in exclude_exts):
                    continue
                
                # 计算文件在压缩包内的相对路径
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(plugin_dir))
                
                # 写入压缩包
                zipf.write(file_path, arcname)
                print(f"  Added: {arcname}")

    print(f"\nBuild successful! Distribution package created at: {os.path.abspath(output_zip)}")
    print("Users can now install this ZIP file via QGIS -> Plugins -> Manage and Install Plugins -> Install from ZIP")

if __name__ == '__main__':
    build_plugin()
