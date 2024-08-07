import paho.mqtt.client as mqtt
import subprocess
import time
from PIL import Image
import io
import schedule
import datetime
import logging
from logging.handlers import RotatingFileHandler
import sys
import os

# 设置日志级别
LOGGING_LEVEL = os.environ.get('LOGGING_LEVEL', 'INFO')
logging.basicConfig(level=getattr(logging, LOGGING_LEVEL))

# MQTT设置
MQTT_BROKER = os.environ.get('MQTT_BROKER', '192.168.11.5')
MQTT_PORT = int(os.environ.get('MQTT_PORT', 21883))
MQTT_TOPIC = "home/doorlock/set"
MQTT_STATE_TOPIC = "home/doorlock/state"

# ADB设置
ADB_DEVICE = os.environ.get('ADB_DEVICE', '192.168.11.135:5555')

# 点击坐标（根据您的应用界面调整）
UNLOCK_COORDS = "750 1200"        # 解锁按钮的x y坐标
LOCK_COORDS = "330 1200"          # 锁定按钮的x y坐标
RELEASE_SLEEP_MODE = "530 1440"   # 解除睡眠按钮的x y坐标

# 颜色检查坐标和阈值
COLOR_CHECK_COORDS = "140 380"
UNLOCK_COLOR = (194, 23, 45)     # 未锁定状态的红色阈值
LOCKED_COLOR = (0, 168, 135)     # 锁定状态的绿色阈值
UNLINKED_COLOR = (130, 130, 130) # 未连接锁时的灰色阈值
COLOR_TOLERANCE = 10                  # 定义颜色匹配的容差

# 全局变量用于存储MQTT客户端
mqtt_client = None

def setup_logging():
    """配置日志系统"""
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    # 获取当前脚本的目录
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    LOG_FILE = os.path.join(CURRENT_DIR, 'doorlock.log')
    
    # 创建一个 RotatingFileHandler
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(LOGGING_LEVEL)
    
    # 创建一个 StreamHandler 用于控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(LOGGING_LEVEL)
    
    # 获取根日志记录器并添加处理器
    root_logger = logging.getLogger()
    root_logger.setLevel(LOGGING_LEVEL)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

def turn_off_screen():
    """关闭手机屏幕函数"""
    cmd = f"adb -s {ADB_DEVICE} shell CLASSPATH=/mnt/sdcard/Documents/DisplayToggle.dex app_process / DisplayToggle 0"
    try:
        result = subprocess.run(cmd, shell=True, check=False, capture_output=True, text=True)
        if "Display mode: 0" in result.stdout:
            logging.info("成功关闭手机屏幕")
            return True
        else:
            logging.error(f"关闭手机屏幕失败: {result.stdout}")
            return False
    except Exception as e:
        logging.error(f"执行关闭手机屏幕命令时发生错误: {e}")
        return False

def on_connect(client, userdata, flags, rc, properties=None):
    """MQTT连接成功后的回调函数"""
    logging.info(f"Connected with result code {rc}")
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    """接收到MQTT消息后的回调函数"""
    logging.info(f"Received message: {msg.topic} {str(msg.payload)}")
    if msg.payload == b"UNLOCK":
        control_lock("unlock", client)
    elif msg.payload == b"LOCK":
        control_lock("lock", client)

def capture_screen():
    """捕获Android设备屏幕截图"""
    cmd = f"adb -s {ADB_DEVICE} exec-out screencap -p"
    result = subprocess.run(cmd, shell=True, capture_output=True)
    return Image.open(io.BytesIO(result.stdout))

def release_sleep_mode():
    """解除Android设备的睡眠模式"""
    cmd_release_sleep = f"adb -s {ADB_DEVICE} shell input tap {RELEASE_SLEEP_MODE}"
    try:
        subprocess.run(cmd_release_sleep, shell=True, check=True)
        logging.info("执行【スリープモード解除】操作成功")
        time.sleep(3)  # 等待3秒
    except subprocess.CalledProcessError as e:
        logging.error(f"执行【スリープモード解除】操作失败: {e}")

def check_lock_status():
    """检查门锁状态"""
    release_sleep_mode()
    image = capture_screen()
    pixel = image.getpixel(tuple(map(int, COLOR_CHECK_COORDS.split())))
    logging.info(f"Detected color at check coordinates: {pixel}")

    def color_matches(color1, color2, tolerance):
        return all(abs(c1 - c2) <= tolerance for c1, c2 in zip(color1[:3], color2[:3]))

    if color_matches(pixel, UNLOCK_COLOR, COLOR_TOLERANCE):
        logging.info("检测到未锁定状态（红色）")
        return "unlocked"
    elif color_matches(pixel, LOCKED_COLOR, COLOR_TOLERANCE):
        logging.info("检测到锁定状态（绿色）")
        return "locked"
    elif color_matches(pixel, UNLINKED_COLOR, COLOR_TOLERANCE):
        logging.warning("检测到未连接状态（灰色）")
        return "unlinked"
    else:
        logging.warning(f"无法匹配颜色: {pixel}")
        return "unknown"

def control_lock(action, client, retry=True):
    """控制门锁的锁定或解锁"""
    release_sleep_mode()

    coords = UNLOCK_COORDS if action == "unlock" else LOCK_COORDS
    cmd = f"adb -s {ADB_DEVICE} shell input tap {coords}"
    try:
        subprocess.run(cmd, shell=True, check=True)
        logging.info(f"执行{action}操作")
        time.sleep(2)  # 等待操作完成
        
        status = check_lock_status()
        if status == "unlinked":
            logging.warning("门锁未连接,无法执行操作")
            client.publish(MQTT_STATE_TOPIC, "UNLINKED")
        elif (action == "unlock" and status == "unlocked") or (action == "lock" and status == "locked"):
            logging.info(f"{action}操作成功")
            client.publish(MQTT_STATE_TOPIC, status.upper())
        elif retry:
            logging.warning(f"{action}操作未成功,重试")
            control_lock(action, client, retry=False)  # 重试一次
        else:
            logging.error(f"{action}操作失败")
            client.publish(MQTT_STATE_TOPIC, "UNKNOWN")
    except subprocess.CalledProcessError as e:
        logging.error(f"执行{action}操作失败: {e}")
        client.publish(MQTT_STATE_TOPIC, "ERROR")

def check_adb_connection():
    """检查ADB连接状态"""
    cmd = f"adb connect {ADB_DEVICE}"
    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        logging.info(f"ADB连接结果: {result.stdout.strip()}")
        return "connected" in result.stdout.lower()
    except subprocess.CalledProcessError as e:
        logging.error(f"ADB连接失败: {e}")
        return False

def periodic_status_check():
    """定期检查门锁状态的函数"""
    current_time = datetime.datetime.now().time()
    if datetime.time(7, 0) <= current_time <= datetime.time(22, 0):
        status = check_lock_status()
        if status == "unlocked":
            logging.info("定期检查: 门锁已解锁")
            mqtt_client.publish(MQTT_STATE_TOPIC, "UNLOCKED")
        elif status == "locked":
            logging.info("定期检查: 门锁已锁定")
            mqtt_client.publish(MQTT_STATE_TOPIC, "LOCKED")
        elif status == "unlinked":
            logging.warning("定期检查: 门锁未连接")
            mqtt_client.publish(MQTT_STATE_TOPIC, "UNLINKED")
        else:
            logging.warning("定期检查: 无法确定门锁状态")
            mqtt_client.publish(MQTT_STATE_TOPIC, "UNKNOWN")

# 主程序
if __name__ == "__main__":
    # 设置日志
    setup_logging()
    logging.info("Door Lock Control 程序启动")

    # 首先检查并确保ADB连接
    if not check_adb_connection():
        logging.error("无法连接到Android设备，请检查网络连接和ADB设置")
        exit(1)

    # 关闭手机屏幕
    time.sleep(3)
    turn_off_screen()

    # MQTT
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        
        # 设置定时任务，每5分钟执行一次
        schedule.every(5).minutes.do(periodic_status_check)
        
        # 启动MQTT客户端循环
        mqtt_client.loop_start()
        
        # 运行定时任务
        while True:
            schedule.run_pending()
            time.sleep(1)
    except Exception as e:
        logging.error(f"MQTT连接失败: {e}")
        exit(1)