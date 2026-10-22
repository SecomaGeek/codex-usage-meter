import argparse,sys

def main():
    parser=argparse.ArgumentParser(description='Windows用の非公式・読み取り専用Codex利用量メーター')
    parser.add_argument('--mini',action='store_true',help='極小ガジェットで起動')
    parser.add_argument('--demo',action='store_true',help='認証情報・ネットワークを使わずダミーデータで表示')
    args=parser.parse_args()
    if sys.platform!='win32': parser.error('GUIはWindows専用です。')
    from . import ui
    if args.demo:
        from .demo import configure_demo
        configure_demo(ui)
    ui.run_app()

if __name__=='__main__': main()
