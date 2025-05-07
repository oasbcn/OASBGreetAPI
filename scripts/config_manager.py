#!/usr/bin/env python3
"""
配置文件管理工具

功能：
1. 验证配置文件格式
2. 检查配置值的合理性
3. 提供配置文件生成向导
4. 输出配置检查报告
"""

import json
import os
import sys
import argparse
from typing import Dict, Any, List, Tuple

class ConfigValidator:
    """配置文件验证器"""
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    def validate_server(self, config: Dict[str, Any]) -> bool:
        """验证服务器配置"""
        server = config.get('server', {})
        
        # 检查必需字段
        required_fields = ['host', 'port']
        for field in required_fields:
            if field not in server:
                self.errors.append(f"服务器配置缺少必需字段: {field}")
        
        # 验证端口范围
        if 'port' in server:
            port = server['port']
            if not isinstance(port, int) or port < 1 or port > 65535:
                self.errors.append(f"无效的端口号: {port}，端口号必须在1-65535之间")
        
        # 检查debug模式
        if server.get('debug', False):
            self.warnings.append("警告: debug模式已启用，不建议在生产环境中使用")
            
        return len(self.errors) == 0
    
    def validate_logging(self, config: Dict[str, Any]) -> bool:
        """验证日志配置"""
        logging = config.get('logging', {})
        
        # 验证日志级别
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if 'level' in logging and logging['level'] not in valid_levels:
            self.errors.append(f"无效的日志级别: {logging['level']}")
        
        # 验证文件配置
        file_config = logging.get('file', {})
        if file_config.get('enabled', False):
            # 检查路径
            path = file_config.get('path', '')
            if not path:
                self.errors.append("日志文件路径不能为空")
            
            # 检查大小格式
            size = file_config.get('max_size', '')
            if not size.endswith(('KB', 'MB', 'GB')):
                self.errors.append(f"无效的日志文件大小格式: {size}")
                
        return len(self.errors) == 0
    
    def validate_monitoring(self, config: Dict[str, Any]) -> bool:
        """验证监控配置"""
        monitoring = config.get('monitoring', {})
        
        # 验证时间间隔
        interval = monitoring.get('interval', 0)
        if interval < 10:
            self.warnings.append(f"监控间隔({interval}秒)可能过短，建议设置为至少10秒")
        
        # 验证保留天数
        retention = monitoring.get('retention', 0)
        if retention < 1:
            self.errors.append("数据保留天数必须大于0")
        elif retention > 90:
            self.warnings.append(f"数据保留时间({retention}天)较长，可能占用大量磁盘空间")
        
        # 验证阈值
        thresholds = monitoring.get('thresholds', {})
        if thresholds.get('cpu', 0) > 90:
            self.warnings.append("CPU使用率阈值过高，可能导致系统响应迟缓")
        
        return len(self.errors) == 0
    
    def validate_security(self, config: Dict[str, Any]) -> bool:
        """验证安全配置"""
        security = config.get('security', {})
        
        # 验证速率限制
        rate_limit = security.get('rate_limit', {})
        if rate_limit.get('enabled', False):
            rpm = rate_limit.get('requests_per_minute', 0)
            if rpm < 30:
                self.warnings.append(f"请求限制({rpm}/分钟)可能过于严格")
            elif rpm > 1000:
                self.warnings.append(f"请求限制({rpm}/分钟)可能过于宽松")
        
        # 验证安全头部
        headers = security.get('headers', {})
        if not headers.get('xss_protection'):
            self.warnings.append("建议启用XSS保护")
        if not headers.get('content_type_options'):
            self.warnings.append("建议启用content-type-options")
            
        return len(self.errors) == 0

def validate_config(config_path: str) -> Tuple[bool, List[str], List[str]]:
    """验证配置文件"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        return False, [f"配置文件JSON格式错误: {str(e)}"], []
    except Exception as e:
        return False, [f"读取配置文件失败: {str(e)}"], []
    
    validator = ConfigValidator()
    
    # 验证各个部分
    validator.validate_server(config)
    validator.validate_logging(config)
    validator.validate_monitoring(config)
    validator.validate_security(config)
    
    return len(validator.errors) == 0, validator.errors, validator.warnings

def create_config_wizard() -> Dict[str, Any]:
    """配置文件生成向导"""
    config = {}
    
    print("\n=== 服务器配置 ===")
    config['server'] = {
        'host': input("请输入服务监听地址 [0.0.0.0]: ") or "0.0.0.0",
        'port': int(input("请输入服务端口 [5000]: ") or "5000"),
        'debug': input("是否启用调试模式 (y/N): ").lower() == 'y',
        'keep_stats': input("是否保留统计信息 (Y/n): ").lower() != 'n'
    }
    
    print("\n=== 日志配置 ===")
    config['logging'] = {
        'level': input("请输入日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL) [INFO]: ") or "INFO",
        'file': {
            'enabled': input("是否启用文件日志 (Y/n): ").lower() != 'n',
            'path': input("请输入日志文件路径 [logs/app.log]: ") or "logs/app.log",
            'max_size': input("请输入日志文件最大大小 [10MB]: ") or "10MB",
            'backup_count': int(input("请输入保留的日志文件数量 [5]: ") or "5")
        }
    }
    
    print("\n=== 监控配置 ===")
    config['monitoring'] = {
        'enabled': input("是否启用监控 (Y/n): ").lower() != 'n',
        'interval': int(input("请输入监控间隔(秒) [60]: ") or "60"),
        'retention': int(input("请输入数据保留天数 [7]: ") or "7"),
        'directory': input("请输入监控数据存储目录 [monitoring]: ") or "monitoring",
        'thresholds': {
            'cpu': int(input("请输入CPU使用率告警阈值(%) [80]: ") or "80"),
            'memory': int(input("请输入内存使用告警阈值(MB) [500]: ") or "500"),
            'disk_read': int(input("请输入磁盘读取速度告警阈值(MB/s) [10]: ") or "10"),
            'disk_write': int(input("请输入磁盘写入速度告警阈值(MB/s) [5]: ") or "5")
        }
    }
    
    print("\n=== 安全配置 ===")
    config['security'] = {
        'rate_limit': {
            'enabled': input("是否启用请求限制 (Y/n): ").lower() != 'n',
            'requests_per_minute': int(input("请输入每分钟最大请求数 [60]: ") or "60")
        },
        'headers': {
            'xss_protection': input("是否启用XSS保护 (Y/n): ").lower() != 'n',
            'frame_options': input("请输入frame-options值 [DENY]: ") or "DENY",
            'content_type_options': input("是否启用content-type-options (Y/n): ").lower() != 'n',
            'hsts': input("请输入HSTS配置 [max-age=31536000]: ") or "max-age=31536000"
        }
    }
    
    return config

def main():
    parser = argparse.ArgumentParser(description="配置文件管理工具")
    parser.add_argument('--validate', '-v', help="验证指定的配置文件")
    parser.add_argument('--create', '-c', help="创建新的配置文件")
    args = parser.parse_args()
    
    if args.validate:
        print(f"\n正在验证配置文件: {args.validate}")
        success, errors, warnings = validate_config(args.validate)
        
        if errors:
            print("\n❌ 发现错误:")
            for error in errors:
                print(f"  • {error}")
        
        if warnings:
            print("\n⚠️ 注意事项:")
            for warning in warnings:
                print(f"  • {warning}")
        
        if success:
            print("\n✅ 配置文件验证通过！")
        sys.exit(0 if success else 1)
    
    elif args.create:
        print("配置文件生成向导")
        config = create_config_wizard()
        
        try:
            with open(args.create, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            print(f"\n✅ 配置文件已生成: {args.create}")
            
            # 验证新生成的配置
            success, errors, warnings = validate_config(args.create)
            if warnings:
                print("\n⚠️ 注意事项:")
                for warning in warnings:
                    print(f"  • {warning}")
        except Exception as e:
            print(f"\n❌ 配置文件生成失败: {str(e)}")
            sys.exit(1)
    
    else:
        parser.print_help()

if __name__ == '__main__':
    main()