# 配置文件说明

## 服务器配置 (server)
```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 5000,
    "debug": false,
    "keep_stats": true
  }
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| host | string | "0.0.0.0" | 服务监听地址，0.0.0.0表示允许所有IP访问 |
| port | number | 5000 | 服务监听端口 |
| debug | boolean | false | 是否启用调试模式，生产环境建议设为false |
| keep_stats | boolean | true | 是否在服务重启时保留统计信息 |

## 日志配置 (logging)
```json
{
  "logging": {
    "level": "INFO",
    "format": "[%(asctime)s] [%(levelname)s] %(message)s",
    "file": {
      "enabled": true,
      "path": "logs/app.log",
      "max_size": "10MB",
      "backup_count": 5
    }
  }
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| level | string | "INFO" | 日志级别：DEBUG, INFO, WARNING, ERROR, CRITICAL |
| format | string | - | 日志格式，支持时间、级别、消息等占位符 |
| file.enabled | boolean | true | 是否启用文件日志 |
| file.path | string | "logs/app.log" | 日志文件路径 |
| file.max_size | string | "10MB" | 单个日志文件的最大大小，超过后会自动轮转 |
| file.backup_count | number | 5 | 保留的日志文件数量 |

## 缓存配置 (cache)
```json
{
  "cache": {
    "enabled": true,
    "type": "simple",
    "default_timeout": 300,
    "threshold": 1000
  }
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| enabled | boolean | true | 是否启用缓存 |
| type | string | "simple" | 缓存类型：simple（简单内存缓存） |
| default_timeout | number | 300 | 缓存默认过期时间（秒） |
| threshold | number | 1000 | 缓存条目数上限，超过后使用LRU策略清理 |

## 监控配置 (monitoring)
```json
{
  "monitoring": {
    "enabled": true,
    "interval": 60,
    "retention": 7,
    "directory": "monitoring",
    "thresholds": {
      "cpu": 80,
      "memory": 500,
      "disk_read": 10,
      "disk_write": 5
    }
  }
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| enabled | boolean | true | 是否启用监控 |
| interval | number | 60 | 监控数据收集间隔（秒） |
| retention | number | 7 | 数据保留天数 |
| directory | string | "monitoring" | 监控数据存储目录 |
| thresholds.cpu | number | 80 | CPU使用率告警阈值（百分比） |
| thresholds.memory | number | 500 | 内存使用告警阈值（MB） |
| thresholds.disk_read | number | 10 | 磁盘读取速度告警阈值（MB/s） |
| thresholds.disk_write | number | 5 | 磁盘写入速度告警阈值（MB/s） |

## 安全配置 (security)
```json
{
  "security": {
    "rate_limit": {
      "enabled": true,
      "requests_per_minute": 60
    },
    "headers": {
      "xss_protection": true,
      "frame_options": "DENY",
      "content_type_options": true,
      "hsts": "max-age=31536000"
    }
  }
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| rate_limit.enabled | boolean | true | 是否启用请求限制 |
| rate_limit.requests_per_minute | number | 60 | 每分钟允许的最大请求数 |
| headers.xss_protection | boolean | true | 是否启用XSS保护 |
| headers.frame_options | string | "DENY" | 禁止页面在iframe中显示 |
| headers.content_type_options | boolean | true | 是否禁止MIME类型嗅探 |
| headers.hsts | string | "max-age=31536000" | HTTPS严格传输安全配置 |