import json
import tempfile
from flask import Flask, request, jsonify, make_response
from flask_caching import Cache
import random
from datetime import datetime, timedelta
import pytz
import uuid
import logging
from colorama import init, Fore, Style, Back
import click
import sys
import os
import flask
import flask.cli
import signal
import platform
import time

# 禁用Flask的CLI消息
flask.cli.show_server_banner = lambda *args: None

# 初始化colorama，确保Windows下的颜色支持
init(autoreset=True, convert=True, strip=False)

# 检测系统类型和终端编码
SYSTEM = platform.system().lower()
IS_WINDOWS = SYSTEM == 'windows'

# Windows终端编码设置
if IS_WINDOWS:
    # 设置控制台代码页
    os.system('chcp 65001')
    # 设置终端编码
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# 记录启动时间
START_TIME = datetime.now()

# 跨平台文件锁实现
class FileLock:
    def __init__(self, file_path):
        """初始化文件锁
        Args:
            file_path: 要锁定的文件路径
        """
        self.file_path = file_path
        self.lock_file = f"{file_path}.lock"
        self.file = None
        
    def __enter__(self):
        """进入上下文时获取锁"""
        try:
            if os.name == 'nt':  # Windows
                import msvcrt
                self.file = open(self.lock_file, 'wb')
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:  # Unix/Linux/MacOS
                import fcntl
                self.file = open(self.lock_file, 'w')
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self
        except (IOError, OSError) as e:
            if self.file:
                self.file.close()
            logger.error(f"获取文件锁失败: {str(e)}")
            raise
            
    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文时释放锁"""
        try:
            if self.file:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
                self.file.close()
                try:
                    os.remove(self.lock_file)
                except OSError:
                    pass
        except Exception as e:
            logger.error(f"释放文件锁失败: {str(e)}")

# 全局状态变量
class ServiceStatus:
    def __init__(self):
        """初始化服务状态"""
        self.stats_file = os.path.join(tempfile.gettempdir(), 'flask_api_stats.json')
        self._load_or_init_stats()
        
    def _load_or_init_stats(self):
        """
        从文件加载或初始化服务器统计信息。
        使用FileLock确保并发安全。
        
        如果统计文件存在,则从文件中读取以下统计数据:
        - 启动时间
        - 总请求数
        - 最后请求时间
        - 当前活跃连接数
        - 请求方法统计
        - 状态码统计  
        - 端点访问统计
        - 错误记录
        
        如果文件不存在或加载失败,则调用 _init_stats() 初始化统计数据。
        
        异常:
            如果加载过程发生异常,会记录错误日志并初始化统计数据
        """
        try:
            if os.path.exists(self.stats_file):
                with FileLock(self.stats_file):
                    try:
                        with open(self.stats_file, 'r', encoding='utf-8') as f:
                            stats = json.load(f)
                            self.start_time = datetime.fromisoformat(stats.get('start_time', datetime.now().isoformat()))
                            self.total_requests = stats.get('total_requests', 0)
                            self.last_request_time = datetime.fromisoformat(stats['last_request_time']) if stats.get('last_request_time') else None
                            self.active_connections = stats.get('active_connections', 0)
                            self.request_methods = stats.get('request_methods', {})
                            self.status_codes = stats.get('status_codes', {})
                            self.endpoints = stats.get('endpoints', {})
                            self.errors = stats.get('errors', [])
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.error(f"解析统计文件失败: {str(e)}")
                        self._init_stats()
            else:
                self._init_stats()
        except Exception as e:
            logger.error(f"加载统计信息失败: {str(e)}")
            self._init_stats()

    def _init_stats(self):
        """初始化统计信息"""
        self.start_time = datetime.now()
        self.total_requests = 0
        self.last_request_time = None
        self.active_connections = 0
        self.request_methods = {}
        self.status_codes = {}
        self.endpoints = {}
        self.errors = []
        self._save_stats()

    def _save_stats(self):
        """
        保存统计信息到文件。
        使用FileLock确保并发安全，使用临时文件确保写入原子性。
        """
        temp_file = f"{self.stats_file}.tmp"
        try:
            stats = {
                'start_time': self.start_time.isoformat(),
                'total_requests': self.total_requests,
                'last_request_time': self.last_request_time.isoformat() if self.last_request_time else None,
                'active_connections': self.active_connections,
                'request_methods': self.request_methods,
                'status_codes': self.status_codes,
                'endpoints': self.endpoints,
                'errors': self.errors
            }
            
            with FileLock(self.stats_file):
                # 先写入临时文件
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(stats, f, ensure_ascii=False, indent=2)
                
                # 在Windows上，需要先删除目标文件
                if os.name == 'nt' and os.path.exists(self.stats_file):
                    os.remove(self.stats_file)
                    
                # 原子性地重命名临时文件
                os.replace(temp_file, self.stats_file)
                
        except Exception as e:
            logger.error(f"保存统计信息失败: {str(e)}")
            # 清理临时文件
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass

    def request_started(self):
        """记录请求开始"""
        self.active_connections += 1
        # 记录请求方法
        method = request.method
        self.request_methods[method] = self.request_methods.get(method, 0) + 1
        # 记录端点访问
        endpoint = request.endpoint or 'unknown'
        self.endpoints[endpoint] = self.endpoints.get(endpoint, 0) + 1
        self._save_stats()

    def request_finished(self):
        """记录请求结束"""
        self.active_connections = max(0, self.active_connections - 1)
        self._save_stats()

    def record_request(self):
        """记录新的请求"""
        self.total_requests += 1
        self.last_request_time = datetime.now()
        self._save_stats()

    def record_status_code(self, status_code):
        """记录响应状态码"""
        self.status_codes[str(status_code)] = self.status_codes.get(str(status_code), 0) + 1
        self._save_stats()

    def record_error(self, error_msg):
        """记录错误信息，保留最近的10条"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.errors.insert(0, {'time': timestamp, 'error': error_msg})
        self.errors = self.errors[:10]  # 只保留最近10条错误
        self._save_stats()

    def get_uptime(self):
        """获取服务运行时间
        返回一个timedelta对象，表示从服务启动到现在的时间差
        例如："0:06:43.147818" 表示运行了0小时6分43秒147毫秒
        """
        return datetime.now() - self.start_time

    def get_statistics(self):
        """获取完整的统计信息"""
        # 重新加载统计信息以确保数据最新
        self._load_or_init_stats()
        return {
            "uptime": str(self.get_uptime()),
            "total_requests": self.total_requests,
            "active_connections": self.active_connections,
            "last_request": self.last_request_time.strftime('%Y-%m-%d %H:%M:%S') if self.last_request_time else None,
            "request_methods": dict(sorted(self.request_methods.items())),
            "status_codes": dict(sorted(self.status_codes.items())),
            "popular_endpoints": dict(sorted(self.endpoints.items(), key=lambda x: x[1], reverse=True)),
            "recent_errors": self.errors
        }

    def reset(self):
        """重置服务状态"""
        self._init_stats()

# 监控数据存储
class MonitoringDataStore:
    def __init__(self):
        """初始化监控数据存储"""
        self.monitoring_dir = "monitoring"
        self.ensure_dir_exists()
        
    def ensure_dir_exists(self):
        """确保监控目录存在"""
        if not os.path.exists(self.monitoring_dir):
            os.makedirs(self.monitoring_dir)
    
    def get_current_date_file(self):
        """获取当前日期的监控文件路径"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.monitoring_dir, f"monitoring-{date_str}.json")
    
    def save_metrics(self, metrics):
        """保存监控指标"""
        try:
            file_path = self.get_current_date_file()
            with FileLock(file_path):
                # 读取现有数据或初始化新文件
                if os.path.exists(file_path):
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                else:
                    data = {"records": []}
                
                # 添加新记录
                data["records"].append({
                    "timestamp": datetime.now().isoformat(),
                    "metrics": metrics
                })
                
                # 写入文件
                temp_file = f"{file_path}.tmp"
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                # 原子性替换
                if os.path.exists(file_path):
                    os.remove(file_path)
                os.rename(temp_file, file_path)
                
        except Exception as e:
            logger.error(f"保存监控数据失败: {str(e)}")
    
    def cleanup_old_data(self, retention_days=7):
        """清理超过保留天数的旧数据"""
        try:
            now = datetime.now()
            for filename in os.listdir(self.monitoring_dir):
                if filename.startswith("monitoring-") and filename.endswith(".json"):
                    # 从文件名提取日期
                    date_str = filename[11:-5]
                    try:
                        file_date = datetime.strptime(date_str, "%Y-%m-%d")
                        if (now - file_date).days > retention_days:
                            file_path = os.path.join(self.monitoring_dir, filename)
                            os.remove(file_path)
                            logger.info(f"清理旧监控文件: {filename}")
                    except ValueError:
                        continue
        except Exception as e:
            logger.error(f"清理旧监控数据失败: {str(e)}")

# 系统资源监控
class SystemMonitor:
    def __init__(self):
        """初始化系统监控"""
        self.last_cpu_times = None
        self.last_disk_io = None
        self.last_check_time = None
        self.data_store = MonitoringDataStore()
        
    def get_cpu_usage(self):
        """获取CPU使用率"""
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=0.1)
            return f"{cpu_percent:.1f}%"
        except Exception as e:
            logger.error(f"获取CPU使用率失败: {str(e)}")
            return "N/A"
            
    def get_memory_usage(self):
        """获取内存使用情况"""
        try:
            import psutil
            memory = psutil.virtual_memory()
            used_mb = memory.used / (1024 * 1024)
            return f"{used_mb:.1f}MB"
        except Exception as e:
            logger.error(f"获取内存使用情况失败: {str(e)}")
            return "N/A"
            
    def get_disk_io(self):
        """获取磁盘I/O统计"""
        try:
            import psutil
            disk_io = psutil.disk_io_counters()
            current_time = time.time()
            
            if self.last_disk_io and self.last_check_time:
                time_delta = current_time - self.last_check_time
                read_speed = (disk_io.read_bytes - self.last_disk_io.read_bytes) / time_delta
                write_speed = (disk_io.write_bytes - self.last_disk_io.write_bytes) / time_delta
                
                self.last_disk_io = disk_io
                self.last_check_time = current_time
                
                return {
                    "read_speed": f"{read_speed / (1024 * 1024):.1f}MB/s",
                    "write_speed": f"{write_speed / (1024 * 1024):.1f}MB/s",
                    "read_count": disk_io.read_count,
                    "write_count": disk_io.write_count
                }
            
            self.last_disk_io = disk_io
            self.last_check_time = current_time
            return {
                "read_speed": "0MB/s",
                "write_speed": "0MB/s",
                "read_count": disk_io.read_count,
                "write_count": disk_io.write_count
            }
        except Exception as e:
            logger.error(f"获取磁盘I/O统计失败: {str(e)}")
            return {
                "read_speed": "N/A",
                "write_speed": "N/A",
                "read_count": 0,
                "write_count": 0
            }
            
    def get_all_metrics(self):
        """获取所有系统指标并保存"""
        metrics = {
            "cpu_usage": self.get_cpu_usage(),
            "memory_usage": self.get_memory_usage(),
            "disk_io": self.get_disk_io(),
            "timestamp": datetime.now().isoformat()
        }
        
        # 保存监控数据
        self.data_store.save_metrics(metrics)
        
        # 每天清理一次旧数据
        if datetime.now().hour == 0 and datetime.now().minute == 0:
            self.data_store.cleanup_old_data()
            
        return metrics

# 创建全局实例
SERVICE_STATUS = ServiceStatus()
SYSTEM_MONITOR = SystemMonitor()

# 配置日志处理器
class CustomFilter(logging.Filter):
    """自定义日志过滤器"""
    def filter(self, record):
        msg = str(record.msg)
        # 过滤掉不需要的消息
        filtered_messages = [
            'WARNING: This is a development server',
            'Restarting with',
            'Debugger is',
            'Debug mode:',
            '* Running on',
            '* Serving Flask app',
            'Press CTRL+C to quit'
        ]
        return not any(m in msg for m in filtered_messages)

class ColoredFormatter(logging.Formatter):
    """自定义的彩色日志格式化器"""
    def format(self, record):
        # 根据日志级别设置不同的颜色
        colors = {
            'WARNING': Fore.YELLOW,
            'ERROR': Fore.RED,
            'DEBUG': Fore.BLUE,
            'INFO': Fore.GREEN,
            'CRITICAL': Fore.RED + Back.WHITE
        }
        
        # 如果是werkzeug的请求日志，使用简化格式
        if 'werkzeug' in record.name and record.levelname == 'INFO':
            if '200' in record.msg:
                prefix = f"{Fore.GREEN}✓{Style.RESET_ALL}"
            elif '404' in record.msg:
                prefix = f"{Fore.YELLOW}⚠{Style.RESET_ALL}"
            elif '500' in record.msg:
                prefix = f"{Fore.RED}✗{Style.RESET_ALL}"
            else:
                prefix = f"{Fore.BLUE}→{Style.RESET_ALL}"
            return f"{prefix} {record.msg}"
            
        color = colors.get(record.levelname, '')
        if color:
            record.msg = f"{color}{record.msg}{Style.RESET_ALL}"
        return super().format(record)

def format_timedelta(td):
    """格式化时间差"""
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    if hours > 0:
        return f"{hours}小时{minutes}分{seconds}秒"
    elif minutes > 0:
        return f"{minutes}分{seconds}秒"
    else:
        return f"{seconds}秒"

def print_stop_banner(stop_time, is_error=False):
    """打印停止服务的横幅
    参数:
        stop_time: 停止时间
        is_error: 是否因错误而停止
    显示内容包括:
        - 停止状态（正常/异常）
        - 运行时长
        - 启动和停止时间
        - 详细的请求统计信息
    """
    # 获取完整的统计信息
    stats = SERVICE_STATUS.get_statistics()
    runtime = SERVICE_STATUS.get_uptime()
    hours, remainder = divmod(runtime.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    
    status = f"{Fore.RED}异常终止 ✗{Style.RESET_ALL}" if is_error else f"{Fore.GREEN}正常停止 ✓{Style.RESET_ALL}"
    
    # 格式化请求方法统计
    method_stats = "\n".join([f"{Fore.BLUE}▸ {method}: {count}" for method, count in stats["request_methods"].items()])
    
    # 格式化状态码统计
    status_stats = "\n".join([f"{Fore.BLUE}▸ {code}: {count}" for code, count in stats["status_codes"].items()])
    
    # 格式化热门端点统计
    endpoint_stats = "\n".join([f"{Fore.BLUE}▸ {endpoint}: {count}" for endpoint, count in stats["popular_endpoints"].items()])
    
    banner = f"""
{Fore.CYAN}═════════════════════════════════════{Style.RESET_ALL}
{Fore.YELLOW}           服务终止通知           {Style.RESET_ALL}
{Fore.CYAN}═════════════════════════════════════{Style.RESET_ALL}

{Fore.BLUE}▸ 终止状态: {status}
{Fore.BLUE}▸ 服务版本: {API_VERSION}
{Fore.BLUE}▸ 运行时长: {int(hours)}小时 {int(minutes)}分 {int(seconds)}秒

{Fore.MAGENTA}▸ 启动时间: {SERVICE_STATUS.start_time.strftime('%Y-%m-%d %H:%M:%S')}
{Fore.MAGENTA}▸ 停止时间: {stop_time.strftime('%Y-%m-%d %H:%M:%S')}

{Fore.CYAN}═════════════════════════════════════{Style.RESET_ALL}
{Fore.YELLOW}           基本统计信息           {Style.RESET_ALL}
{Fore.CYAN}═════════════════════════════════════{Style.RESET_ALL}

{Fore.BLUE}▸ 累计处理请求: {stats["total_requests"]}
{Fore.BLUE}▸ 最后请求时间: {stats["last_request"] if stats["last_request"] else '无'}

{Fore.CYAN}═════════════════════════════════════{Style.RESET_ALL}
{Fore.YELLOW}           详细统计信息           {Style.RESET_ALL}
{Fore.CYAN}═════════════════════════════════════{Style.RESET_ALL}

{Fore.GREEN}HTTP方法统计:{Style.RESET_ALL}
{method_stats if method_stats else f"{Fore.BLUE}▸ 暂无请求记录"}

{Fore.GREEN}状态码统计:{Style.RESET_ALL}
{status_stats if status_stats else f"{Fore.BLUE}▸ 暂无状态码记录"}

{Fore.GREEN}热门端点统计:{Style.RESET_ALL}
{endpoint_stats if endpoint_stats else f"{Fore.BLUE}▸ 暂无端点访问记录"}

{Fore.CYAN}=========================================={Style.RESET_ALL}
{Fore.YELLOW}     感谢使用 OASB GreetAPI 服务      {Style.RESET_ALL}
{Fore.CYAN}=========================================={Style.RESET_ALL}
"""
    click.echo(banner)

def handle_exit(signum, frame):
    """处理退出信号
    确保服务优雅地停止，只显示一次终止通知
    """
    # 检查是否是主进程
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        print_stop_banner(datetime.now())
    sys.exit(0)

# 配置日志
def setup_logging():
    """配置日志系统"""
    # 创建logs目录
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 创建处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ColoredFormatter('%(message)s'))
    console_handler.addFilter(CustomFilter())
    
    # 创建文件处理器
    app_file_handler = logging.FileHandler(os.path.join(log_dir, 'app.log'), encoding='utf-8')
    app_file_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(process)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    error_file_handler = logging.FileHandler(os.path.join(log_dir, 'error.log'), encoding='utf-8')
    error_file_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(process)d] %(message)s\n%(pathname)s:%(lineno)d\n',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    error_file_handler.setLevel(logging.ERROR)
    
    performance_file_handler = logging.FileHandler(os.path.join(log_dir, 'performance.log'), encoding='utf-8')
    performance_file_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    # 配置werkzeug日志
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.handlers.clear()
    werkzeug_logger.addHandler(console_handler)
    werkzeug_logger.addHandler(app_file_handler)
    werkzeug_logger.setLevel(logging.ERROR)
    
    # 配置应用日志
    app_logger = logging.getLogger('app')
    app_logger.handlers.clear()
    app_logger.addHandler(console_handler)
    app_logger.addHandler(app_file_handler)
    app_logger.addHandler(error_file_handler)
    app_logger.setLevel(logging.INFO)
    
    # 配置性能日志
    perf_logger = logging.getLogger('performance')
    perf_logger.handlers.clear()
    perf_logger.addHandler(performance_file_handler)
    perf_logger.setLevel(logging.INFO)
    perf_logger.propagate = False
    
    # 配置Flask日志
    flask_logger = logging.getLogger('flask')
    flask_logger.handlers.clear()
    flask_logger.addHandler(console_handler)
    flask_logger.addHandler(app_file_handler)
    flask_logger.addHandler(error_file_handler)
    flask_logger.setLevel(logging.ERROR)
    
    return app_logger, perf_logger

logger = setup_logging()

# 配置缓存
cache_config = {
    "CACHE_TYPE": "SimpleCache",
    "CACHE_DEFAULT_TIMEOUT": 300
}

app = Flask(__name__)
app.config.update(cache_config)
app.logger.handlers.clear()
cache = Cache(app)

# JSON和编码配置
app.config.update({
    'JSONIFY_PRETTYPRINT_REGULAR': True,  # 启用JSON自动格式化
    'JSON_SORT_KEYS': False,  # 保持JSON键的原始顺序
    'JSON_AS_ASCII': False,  # 允许JSON包含非ASCII字符
    'JSONIFY_MIMETYPE': "application/json; charset=utf-8",  # 设置正确的MIME类型
})

# 设置默认编码
import sys
if sys.version_info[0] < 3:
    reload(sys)
    sys.setdefaultencoding('utf-8')

@app.before_request
def before_request():
    """请求前处理：记录请求开始并更新统计
    所有请求都会被记录，包括：
    - API请求
    - 静态文件请求
    - 404和其他错误请求
    """
    # 记录请求开始，更新活跃连接数和请求方法统计
    SERVICE_STATUS.request_started()
    # 记录新请求，更新总请求数和最后请求时间
    SERVICE_STATUS.record_request()

@app.after_request
def after_request(response):
    """请求后处理：更新请求统计
    记录响应状态码并更新连接状态
    """
    SERVICE_STATUS.record_status_code(response.status_code)
    SERVICE_STATUS.request_finished()
    return response

@app.teardown_request
def teardown_request(exception=None):
    """请求结束处理：确保连接状态正确更新
    记录错误信息并更新连接状态
    即使发生异常也会执行，确保连接计数准确
    """
    if exception:
        error_msg = str(exception)
        logger.error(f"请求处理发生错误: {error_msg}")
        SERVICE_STATUS.record_error(error_msg)
    SERVICE_STATUS.request_finished()

# API版本控制
API_VERSION = "v1.2.0"
app.config['JSON_AS_ASCII'] = False  # 支持中文
app.config['JSONIFY_MIMETYPE'] = "application/json;charset=utf-8"

# 定义一些有趣的常量
GREETINGS = [
    "你好呀", "嗨！", "很高兴见到你", "欢迎", "哈喽", 
    "今天也要加油哦", "愿你开心每一天", "让我们开始美好的一天"
]

EMOJIS = [
    "👋", "🌟", "✨", "🎉","☀️", "🌙", "⭐", 
    "🎨", "🎭", "🎪", "🎡","⚡", "🧨", "🎲"
]

TIPS = [
    "记得喝水哦 💧",
    "工作之余要适当休息 ⏰",
    "保持微笑，保持快乐 😊",
    "试着做些新鲜事物 🎨",
    "来听听音乐放松一下 🎶",
    "记得每天运动一下哦 🏃‍♂️",
    "保持学习，保持进步 📚",
    "享受生活的每一刻 ⭐"
]

QUOTES = [
    "生活就像一盒巧克力，你永远不知道下一块是什么味道 🍫",
    "每一个今天都是成为更好的自己的机会 ✨",
    "保持热爱，奔赴山海 ⛰️",
    "简单的事重复做，重复的事用心做 💫",
    "当你想放弃的时候，想想是什么让你当初开始 💪",
    "做你自己，成为独特的那个人 🌟",
    "生活不是等待暴风雨过去，而是学会在雨中跳舞 🌧️",
    "微笑着面对它，消除恐惧的最好办法就是面对恐惧 🌈"
]

def get_system_compatible_emoji(emoji_map):
    """根据系统类型返回合适的表情符号
    Windows系统使用简单符号，其他系统使用emoji
    """
    if IS_WINDOWS:
        return emoji_map.get('simple', '')
    return emoji_map.get('emoji', '')

def print_banner(host='localhost', port=5000, is_debug=False):
    """打印美化的启动横幅，确保跨平台兼容性"""
    # 获取系统信息
    python_version = sys.version.split()[0]
    flask_version = flask.__version__
    current_time = SERVICE_STATUS.start_time.strftime("%Y-%m-%d %H:%M:%S")
    
    # 定义跨平台表情符号映射
    emoji_map = {
        'star': {'simple': '*', 'emoji': '✨'},
        'rocket': {'simple': '>>', 'emoji': '🚀'},
        'gear': {'simple': '@', 'emoji': '⚙️'},
        'book': {'simple': '[=]', 'emoji': '📚'},
        'link': {'simple': '#', 'emoji': '📚'},
        'info': {'simple': 'i', 'emoji': 'ℹ️'},
    }
    
    banner = f"""
{Fore.CYAN}====================================={Style.RESET_ALL}
{Fore.YELLOW}✨ OASB GreetAPI ({API_VERSION}){Style.RESET_ALL}
{Fore.CYAN}====================================={Style.RESET_ALL}
{Fore.GREEN}[*] 服务状态: {Fore.WHITE}运行中 {Fore.GREEN}●{Style.RESET_ALL}
{Fore.GREEN}[>] 访问地址: {Fore.WHITE}http://{host}:{port}{Style.RESET_ALL}
{Fore.GREEN}[#] API文档: {Fore.WHITE}http://{host}:{port}{Style.RESET_ALL}
{Fore.GREEN}[+] 示例请求: {Fore.WHITE}http://{host}:{port}/api/greeting?name=test{Style.RESET_ALL}

{Fore.BLUE}系统信息:{Style.RESET_ALL}
• Python版本: {python_version}
• Flask版本: {flask_version}
• 工作目录: {os.getcwd()}
• 启动时间: {current_time}
• 运行模式: {'调试模式 🔍' if is_debug else '生产模式 🐝'}

{Fore.MAGENTA}服务统计:{Style.RESET_ALL}
• 累计请求: {SERVICE_STATUS.total_requests}
• 活跃连接: {SERVICE_STATUS.active_connections}
• 最后请求: {SERVICE_STATUS.last_request_time.strftime('%Y-%m-%d %H:%M:%S') if SERVICE_STATUS.last_request_time else '暂无'}

{Fore.YELLOW}操作提示:{Style.RESET_ALL}
• 按 Ctrl+C 停止服务
• 访问 /status 查看实时状态

{Fore.CYAN}====================================={Style.RESET_ALL}
"""
    click.echo(banner)

def get_greeting_by_time():
    """根据时间返回适当的问候语"""
    china_tz = pytz.timezone('Asia/Shanghai')
    current_time = datetime.now(china_tz)
    hour = current_time.hour
    
    if 5 <= hour < 12:
        return "早上好", "🖼️"
    elif 12 <= hour < 14:
        return "中午好", "🌞"
    elif 14 <= hour < 18:
        return "下午好", "☀️"
    elif 18 <= hour < 22:
        return "晚上好", "🌃"
    else:
        return "夜深了", "🌙"

def get_mood_index():
    """生成今日心情指数"""
    return random.randint(80, 100)

@app.route('/')
def index():
    """首页：显示API使用说明"""
    return jsonify({
        "api_name": "✨ OASB GreetAPI",
        "description": "基于Flask的智能问候服务平台，每次请求都会收到独特的回应",
        "endpoints": {
            "基础问候": "/api/greeting?name=你的名字",
            "示例": "/api/greeting?name=小明"
        },
        "features": [
            "🎈 根据时间智能问候",
            "🎲 随机温馨提示",
            "📝 每日随机格言",
            "🌈 心情指数",
            "🎨 丰富的表情"
        ],
        "tips": "复制上面的地址到浏览器试试看吧~",
        "support": "支持中文和表情符号，每次都有不同惊喜 ✨"
    })

@app.route('/status')
def service_status():
    """服务状态检查接口
    返回当前服务的详细运行状态，包括：
    - 基本信息：运行时长、启动时间、版本等
    - 请求统计：总数、活跃连接数、最后请求时间
    - 详细统计：请求方法分布、状态码统计、热门端点
    - 系统资源：CPU、内存、磁盘使用情况
    - 错误信息：最近的错误记录
    """
    # 获取完整统计信息
    stats = SERVICE_STATUS.get_statistics()
    
    # 获取系统资源信息
    system_metrics = SYSTEM_MONITOR.get_all_metrics()
    
    return jsonify({
        "status": "running",
        "version": API_VERSION,
        "start_time": SERVICE_STATUS.start_time.strftime('%Y-%m-%d %H:%M:%S'),
        
        # 基本统计
        "basic_stats": {
            "uptime": stats["uptime"],
            "total_requests": stats["total_requests"],
            "active_connections": stats["active_connections"],
            "last_request": stats["last_request"]
        },
        
        # 详细统计
        "detailed_stats": {
            "request_methods": stats["request_methods"],
            "status_codes": stats["status_codes"],
            "popular_endpoints": stats["popular_endpoints"]
        },
        
        # 系统资源
        "system_metrics": {
            "cpu_usage": system_metrics["cpu_usage"],
            "memory_usage": system_metrics["memory_usage"],
            "disk_io": system_metrics["disk_io"]
        },
        
        # 错误信息
        "recent_errors": stats["recent_errors"] if stats["recent_errors"] else "无错误记录"
    })

@app.route('/api/greeting')
@cache.cached(timeout=60, query_string=True)  # 缓存1分钟
def greeting():
    """处理问候请求，确保正确处理Unicode字符"""
    # 设置响应编码
    flask.Flask.response_class.charset = 'utf-8'
    
    # 设置响应头，确保正确的字符编码
    response = make_response()
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    """处理问候请求
    返回个性化的问候消息，包括：
    - 基于时间的问候语
    - 心情指数
    - 温馨提示
    - 励志名言
    请求统计由中间件自动处理
    """
    # 生成唯一会话ID
    session_id = str(uuid.uuid4())[:8]
    
    # 获取并处理参数，确保正确的Unicode编码
    name = request.args.get('name', type=str)
    if name:
        try:
            # 确保name是有效的UTF-8字符串
            name = name.encode('utf-8').decode('utf-8')
        except UnicodeError:
            name = None
    
    favorite = request.args.get('favorite', '').lower()
    
    # 获取时间相关问候
    time_greeting, time_emoji = get_greeting_by_time()
    
    # 构建优化后的响应结构
    status = "success" if name and name.strip() else "info"
    response_data = {
        "code": 200,
        "status": status,
        "data": {
            "greeting": f"{time_greeting} {time_emoji} {random.choice(GREETINGS)} {random.choice(EMOJIS)}",
            "mood": f"{get_mood_index()}% {random.choice(['😊', '🥳', '🌟', '✨'])}",
            "tip": random.choice(TIPS),
            "quote": random.choice(QUOTES)
        },
        "meta": {
            "api_version": API_VERSION,
            "session_id": session_id,
            "timestamp": datetime.now(pytz.timezone('Asia/Shanghai')).strftime("%Y-%m-%d %H:%M:%S")
        }
    }

    # 创建响应对象，确保正确处理Unicode字符
    response = make_response(jsonify(response_data))
    response.headers.update({
        'Content-Type': 'application/json; charset=utf-8',
        'Access-Control-Allow-Origin': '*',  # 允许跨域访问
        'Access-Control-Allow-Methods': 'GET',
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY'
    })
    
    # 设置缓存控制
    if cache.cached:
        response.headers['Cache-Control'] = 'public, max-age=60'
    else:
        response.headers['Cache-Control'] = 'no-store'

    # 未提供name参数的情况
    if name is None:
        response_data["data"]["example"] = "http://localhost:5000/api/greeting?name=小明"
        return make_response(jsonify(response_data), 200)
    
    # 验证name参数
    name = name.strip()
    if not name:
        response_data.update({
            "code": 400,
            "status": "error",
            "error": {
                "code": "InvalidParameter",
                "message": "name参数不能为空",
                "suggestion": "请提供有效的名字参数"
            }
        })
        return make_response(jsonify(response_data), 400)
    
    # 添加个性化内容
    response_data["data"]["greeting"] += f", {name}！"
    
    # 添加用户喜好相关的内容
    if favorite:
        favorite_responses = {
            'music': f"🎵 听说你喜欢音乐，今天推荐: {random.choice(['古典', '流行', '爵士'])}",
            'sports': f"⚽ 运动爱好者！今天适合: {random.choice(['跑步', '瑜伽', '游泳'])}",
            'food': f"🍄‍ 美食家！试试: {random.choice(['川菜', '粤菜', '湘菜'])}"
        }
        response_data["data"]["recommendation"] = favorite_responses.get(favorite, "🎁 发现你的独特喜好！")
    
    return make_response(jsonify(response_data), 200)

def cleanup_stats_file():
    """清理统计文件"""
    try:
        stats_file = os.path.join(tempfile.gettempdir(), 'flask_api_stats.json')
        if os.path.exists(stats_file):
            os.remove(stats_file)
    except Exception as e:
        logger.error(f"清理统计文件失败: {str(e)}")

if __name__ == '__main__':
    import argparse
    
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description='OASB GreetAPI 服务')
    parser.add_argument('--host', default='0.0.0.0', help='服务监听地址 (默认: 0.0.0.0，允许所有设备访问)')
    parser.add_argument('--port', type=int, default=5000, help='服务端口 (默认: 5000)')
    parser.add_argument('--debug', action='store_true', help='启用调试模式')
    parser.add_argument('--keep-stats', action='store_true', help='保留上次运行的统计信息')
    
    # 解析命令行参数
    args = parser.parse_args()
    
    # 注册信号处理器
    signal.signal(signal.SIGINT, handle_exit)
    
    try:
        # 清理旧的统计文件（除非指定保留）
        if not args.keep_stats and not os.environ.get('WERKZEUG_RUN_MAIN'):
            cleanup_stats_file()
        
        # 获取本机IP地址
        import socket
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        
        # 只在主进程中显示横幅
        if not os.environ.get('WERKZEUG_RUN_MAIN'):
            # 显示本地访问地址
            print_banner(host='localhost', port=args.port, is_debug=args.debug)
            # 开发环境显示网络访问地址
            if args.debug and args.host == '0.0.0.0':
                click.echo(f"\n{Fore.GREEN}📡 本地网络访问地址: {Fore.WHITE}http://{local_ip}:{args.port}{Style.RESET_ALL}")
                click.echo(f"{Fore.YELLOW}开发提示: 仅限内网测试使用{Style.RESET_ALL}\n")
            # 生产环境提示
            elif args.host == '0.0.0.0':
                click.echo(f"\n{Fore.GREEN}🌐 服务已启动，请通过配置的域名或公网IP访问{Style.RESET_ALL}")
                click.echo(f"{Fore.YELLOW}生产提示: 请确保已配置防火墙和安全组规则{Style.RESET_ALL}\n")
        
        # 启动应用
        app.run(
            host=args.host,
            port=args.port,
            debug=args.debug,
            use_reloader=True
        )
    except Exception as e:
        print_stop_banner(datetime.now(), is_error=True)
        logger.error(f"启动服务时发生错误: {str(e)}")
        sys.exit(1)