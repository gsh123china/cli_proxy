#!/usr/bin/env python3
import argparse
import time
from src.codex import ctl as codex
from src.claude import ctl as claude
from src.ui import ctl as ui

def print_status():
    """显示所有服务的运行状态"""
    print("=== 本地代理 服务运行状态 ===\n")
    
    # Claude 服务状态
    print("Claude 代理:")
    claude_running = claude.is_running()
    claude_pid = claude.get_pid() if claude_running else None
    claude_config = claude.claude_config_manager.active_config
    
    status_text = "运行中" if claude_running else "已停止"
    pid_text = f" (PID: {claude_pid})" if claude_pid else ""
    config_text = f" - 激活配置: {claude_config}" if claude_config else " - 无可用配置"

    print(f"  端口: 3210")
    print(f"  状态: {status_text}{pid_text}")
    print(f"  配置: {config_text}")
    print()
    
    # Codex 服务状态  
    print("Codex 代理:")
    codex_running = codex.is_running()
    codex_pid = codex.get_pid() if codex_running else None
    codex_config = codex.codex_config_manager.active_config
    
    status_text = "运行中" if codex_running else "已停止"
    pid_text = f" (PID: {codex_pid})" if codex_pid else ""
    config_text = f" - 激活配置: {codex_config}" if codex_config else " - 无可用配置"

    print(f"  端口: 3211")
    print(f"  状态: {status_text}{pid_text}")
    print(f"  配置: {config_text}")
    print()

    # UI 服务状态
    print("UI 服务:")
    ui_running = ui.is_running()
    ui_pid = ui.get_pid() if ui_running else None
    
    status_text = "运行中" if ui_running else "已停止"
    pid_text = f" (PID: {ui_pid})" if ui_pid else ""

    print(f"  端口: 3300")
    print(f"  状态: {status_text}{pid_text}")

def main():
    """主函数 - 处理命令行参数"""
    parser = argparse.ArgumentParser(
        description='CLI Proxy - 本地AI代理服务控制工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""使用示例:
  clp start                     启动所有服务
  clp stop                      停止所有服务
  clp status                    查看所有服务状态
  clp list claude               列出Claude的所有配置
  clp active claude prod        激活Claude的prod配置""",
        prog='clp'
    )
    subparsers = parser.add_subparsers(
        dest='command', 
        title='可用命令',
        description='使用 clp <命令> --help 查看具体命令的详细帮助',
        help='命令说明'
    )
    
    # start 命令
    start = subparsers.add_parser(
        'start', 
        help='启动所有代理服务',
        description='启动codex、claude和ui三个服务',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  clp start                     启动所有服务(codex:3211, claude:3210, ui:3300)"""
    )
    
    # stop 命令
    stop = subparsers.add_parser(
        'stop', 
        help='停止所有代理服务',
        description='停止codex、claude和ui三个服务'
    )
    
    # restart 命令
    restart = subparsers.add_parser(
        'restart', 
        help='重启所有代理服务',
        description='重启codex、claude和ui三个服务',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  clp restart                   重启所有服务"""
    )
    
    # active 命令
    active_parser = subparsers.add_parser(
        'active', 
        help='激活指定配置',
        description='设置要使用的配置文件',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  clp active claude prod        激活Claude的prod配置
  clp active codex dev          激活Codex的dev配置"""
    )
    active_parser.add_argument('service', choices=['codex', 'claude'], 
                              help='服务类型', metavar='{codex,claude}')
    active_parser.add_argument('config_name', help='要激活的配置名称')
    
    # list 命令
    lists = subparsers.add_parser(
        'list', 
        help='列出所有配置',
        description='显示指定服务的所有可用配置'
    )
    lists.add_argument('service', choices=['codex', 'claude'], 
                      help='服务类型', metavar='{codex,claude}')
    
    # status 命令
    status_parser = subparsers.add_parser(
        'status', 
        help='显示服务状态',
        description='显示所有代理服务的运行状态、PID和激活配置信息'
    )
    
    # ui 命令
    ui_parser = subparsers.add_parser(
        'ui',
        help='启动Web UI界面',
        description='启动Web UI界面来可视化代理状态',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  clp ui                        启动UI界面(默认端口3300)"""
    )

    # auth 命令组
    auth_parser = subparsers.add_parser(
        'auth',
        help='鉴权管理',
        description='管理API鉴权token和配置',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  clp auth generate --name prod              生成新token
  clp auth list                              列出所有token
  clp auth on                                启用鉴权
  clp auth off                               关闭鉴权
  clp auth enable prod                       启用指定token
  clp auth disable prod                      禁用指定token
  clp auth remove prod                       删除指定token"""
    )

    auth_subparsers = auth_parser.add_subparsers(
        dest='auth_command',
        title='鉴权命令',
        help='鉴权子命令'
    )

    # auth generate - 生成token
    auth_generate = auth_subparsers.add_parser(
        'generate',
        help='生成新的鉴权token',
        description='生成一个新的随机token用于API鉴权'
    )
    auth_generate.add_argument('--name', required=True, help='token名称（唯一标识）')
    auth_generate.add_argument('--description', default='', help='token描述信息')
    auth_generate.add_argument('--expires', help='过期时间（ISO格式，如 2025-12-31T23:59:59）')
    auth_generate.add_argument(
        '--services',
        nargs='+',
        choices=['ui', 'claude', 'codex'],
        help='允许访问的服务，默认覆盖全部服务'
    )

    # auth list - 列出所有token
    auth_list = auth_subparsers.add_parser(
        'list',
        help='列出所有token',
        description='显示所有已配置的鉴权token'
    )

    # auth on - 启用鉴权
    auth_on = auth_subparsers.add_parser(
        'on',
        help='启用鉴权',
        description='启用全局鉴权功能（需要重启服务）'
    )

    # auth off - 关闭鉴权
    auth_off = auth_subparsers.add_parser(
        'off',
        help='关闭鉴权',
        description='关闭全局鉴权功能（需要重启服务）'
    )

    # auth enable - 启用指定token
    auth_enable = auth_subparsers.add_parser(
        'enable',
        help='启用指定token',
        description='启用一个已禁用的token'
    )
    auth_enable.add_argument('name', help='token名称')

    # auth disable - 禁用指定token
    auth_disable = auth_subparsers.add_parser(
        'disable',
        help='禁用指定token',
        description='禁用一个token（不删除）'
    )
    auth_disable.add_argument('name', help='token名称')

    # auth remove - 删除token
    auth_remove = auth_subparsers.add_parser(
        'remove',
        help='删除指定token',
        description='永久删除一个token'
    )
    auth_remove.add_argument('name', help='token名称')

    # 解析参数
    args = parser.parse_args()

    if args.command == 'start':
        print("正在启动所有服务...")
        claude.start()
        codex.start()
        ui.start()
        
        # 等待服务启动
        time.sleep(1)
        print("启动完成!")
        print_status()
    elif args.command == 'stop':
        claude.stop()
        codex.stop()
        ui.stop()
    elif args.command == 'restart':
        claude.restart()
        codex.restart()
        ui.restart()
    elif args.command == 'active':
        if args.service == 'codex':
            codex.set_active_config(args.config_name)
        elif args.service == 'claude':
            claude.set_active_config(args.config_name)
    elif args.command == 'list':
        if args.service == 'codex':
            codex.list_configs()
        elif args.service == 'claude':
            claude.list_configs()
    elif args.command == 'status':
        print_status()
    elif args.command == 'ui':
        import webbrowser
        webbrowser.open("http://localhost:3300")
    elif args.command == 'auth':
        handle_auth_command(args)
    else:
        parser.print_help()


def handle_auth_command(args):
    """处理 auth 命令"""
    from src.auth.auth_manager import AuthManager
    from src.auth.token_generator import generate_token
    from datetime import datetime

    auth_manager = AuthManager()

    if args.auth_command == 'generate':
        # 生成新token
        token = generate_token()
        success = auth_manager.add_token(
            token=token,
            name=args.name,
            description=args.description,
            expires_at=args.expires,
            services=args.services
        )

        if success:
            print(f"✓ Token 生成成功！")
            print(f"名称: {args.name}")
            print(f"Token: {token}")
            services_display = ', '.join(args.services) if args.services else 'ui, claude, codex'
            print(f"服务: {services_display}")
            print(f"\n请妥善保管此token，它将用于访问代理服务。")
            if args.expires:
                print(f"过期时间: {args.expires}")

            # 检查鉴权是否启用
            if not auth_manager.is_enabled():
                print(f"\n提示: 当前鉴权未启用，运行 'clp auth on' 启用鉴权功能。")
        else:
            print(f"✗ Token 生成失败")

    elif args.auth_command == 'list':
        # 列出所有token
        tokens = auth_manager.list_tokens()
        enabled = auth_manager.is_enabled()

        print(f"=== 鉴权Token列表 ===")
        print(f"全局状态: {'已启用' if enabled else '已关闭'}\n")

        if not tokens:
            print("暂无配置的token")
            print("\n运行 'clp auth generate --name <名称>' 创建新token")
        else:
            print(f"{'名称':<15} {'状态':<8} {'服务':<18} {'创建时间':<20} {'描述'}")
            print("-" * 90)
            for token in tokens:
                name = token.get('name', 'N/A')
                active = '启用' if token.get('active', True) else '禁用'
                services = token.get('services')
                if services is None:
                    services_display = 'ui,claude,codex'
                elif services:
                    services_display = ','.join(services)
                else:
                    services_display = 'none'
                created_raw = token.get('created_at', 'N/A')
                created = created_raw[:19] if isinstance(created_raw, str) else 'N/A'
                description = token.get('description', '')
                print(f"{name:<15} {active:<8} {services_display:<18} {created:<20} {description}")

            print(f"\n共 {len(tokens)} 个token")

    elif args.auth_command == 'on':
        # 启用鉴权
        auth_manager.set_enabled(True)
        print("✓ 鉴权已启用")
        print("\n提示: 请重启服务使配置生效: clp restart")

        # 检查是否有可用token
        tokens = auth_manager.list_tokens()
        if not tokens:
            print("\n警告: 尚未配置任何token，运行 'clp auth generate --name <名称>' 创建token")

    elif args.auth_command == 'off':
        # 关闭鉴权
        auth_manager.set_enabled(False)
        print("✓ 鉴权已关闭")
        print("\n提示: 请重启服务使配置生效: clp restart")

    elif args.auth_command == 'enable':
        # 启用指定token
        success = auth_manager.set_token_active(args.name, True)
        if success:
            print(f"✓ Token '{args.name}' 已启用")
        else:
            print(f"✗ 操作失败")

    elif args.auth_command == 'disable':
        # 禁用指定token
        success = auth_manager.set_token_active(args.name, False)
        if success:
            print(f"✓ Token '{args.name}' 已禁用")
        else:
            print(f"✗ 操作失败")

    elif args.auth_command == 'remove':
        # 删除token
        success = auth_manager.remove_token(args.name)
        if success:
            print(f"✓ Token '{args.name}' 已删除")
        else:
            print(f"✗ 操作失败")

    else:
        print("未知的auth命令，运行 'clp auth --help' 查看帮助")

if __name__ == '__main__':
    main()
