"""统一启动入口：python start.py，也可在 Windows 中双击运行。"""
from pathlib import Path
import subprocess
import sys


def main():
    print('ABMS Lab 仿真实验平台')
    print('模型：1. 扩展 Schelling（100×100）  2. Covasim 传染病模型  3. 标准 Schelling  4. 鱼群与鲨鱼')
    model = {'1': 'schelling', '2': 'covasim', '3': 'schelling_standard','4':'fish'}.get(input('请选择模型 [默认 1]：').strip() or '1')
    print('方式：1. 浏览器界面  2. 单次无头运行  3. 批量实验')
    command = {'1': 'ui', '2': 'run', '3': 'batch'}.get(input('请选择运行方式 [默认 1]：').strip() or '1')
    if model is None or command is None:
        print('选项无效，请重新启动。')
        return 1
    root = Path(__file__).resolve().parent
    if model == 'schelling_standard' and command == 'batch':
        print('标准模型批量运行请复制 configs/batch_schelling.yaml，并将 base_config 指向 schelling_standard.yaml。')
        return 1
    config = f'configs/{"batch_" if command == "batch" else ""}{model}.yaml'
    if command == 'ui':
        print('服务启动后，请用浏览器打开 http://127.0.0.1:8765；按 Ctrl+C 停止。')
    return subprocess.call([sys.executable, str(root / 'main.py'), command, '--config', config], cwd=root)


if __name__ == '__main__':
    try:
        code = main()
    except KeyboardInterrupt:
        code = 130
    except Exception as error:
        print(f'启动失败：{error}')
        code = 1
    if code != 130:
        input('\n按回车关闭……')
    sys.exit(code)
