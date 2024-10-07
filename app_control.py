import os
import io
import sys
import time
import logging
import datetime
import schedule
import functools
import subprocess
from PIL import Image
import paho.mqtt.client as mqtt
from logging.handlers import RotatingFileHandler

# 设置日志级别
LOGGING_LEVEL = os.environ.get('LOGGING_LEVEL', 'INFO')
logging.basicConfig(level=getattr(logging, LOGGING_LEVEL))

# MQTT设置
MQTT_BROKER = os.environ.get('MQTT_BROKER', '192.168.11.5')
MQTT_PORT = int(os.environ.get('MQTT_PORT', 21883))
MQTT_TOPIC = "home/doorlock/set"
MQTT_STATE_TOPIC = "home/doorlock/state"
MQTT_CHECK_TOPIC = "home/doorlock/check_status"

# ADB设置
ADB_DEVICE = os.environ.get('ADB_DEVICE', '192.168.11.135:5555')
REBOOT_TIME = '03:00'
CHECK_INTERVAL = 30

# 点击坐标（根据您的应用界面调整）
UNLOCK_COORDS = "750 1200"        # 解锁按钮的坐标
LOCK_COORDS = "330 1200"          # 锁定按钮的坐标
RELEASE_SLEEP_MODE = "530 1440"   # 解除睡眠按钮的坐标
LAUNCH_OK_BUTTON = "900 1120"     # 启动时允许使用蓝牙OK按键的坐标

# 颜色检查坐标和阈值
COLOR_CHECK_COORDS = "140 380"
UNLOCK_COLOR = (194, 23, 45)      # 未锁定状态的红色阈值
LOCKED_COLOR = (0, 168, 135)      # 锁定状态的绿色阈值
UNLINKED_COLOR = (130, 130, 130)  # 未连接锁时的灰色阈值
COLOR_TOLERANCE = 10              # 定义颜色匹配的容差

# 定时检查门锁状态时间
START_HOUR = 7
STOP_HOUR = 22

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

def reconnect_adb(device):
    '''重新连接adb'''
    max_attempts = 20
    for attempt in range(max_attempts):
        try:
            subprocess.run(f"adb connect {device}", shell=True, check=True)
            if check_adb_connection():
                logging.info("ADB 重新连接成功")
                return True
        except subprocess.CalledProcessError:
            logging.warning(f"ADB 重连尝试 {attempt + 1} 失败")
        time.sleep(5)
    logging.error("ADB 重连失败")
    return False

def ensure_adb_connection(func):
    '''装饰器用以在执行任何adb命令前先检查adb连接并尝试重连'''
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            if not check_adb_connection():
                logging.warning(f"ADB 连接断开，尝试重新连接...")
                if not reconnect_adb(ADB_DEVICE):
                    logging.error("ADB连接失败, 无法执行操作!")
                    raise
            return func(*args, **kwargs)
        except subprocess.CalledProcessError as e:
            logging.error(f"执行 ADB 命令时出错: {e}")
            raise

    return wrapper

@ensure_adb_connection
def reboot_android_device():
    """重启Android设备"""
    logging.info("正在重启Android设备...")
    cmd = f"adb -s {ADB_DEVICE} reboot"
    try:
        subprocess.run(cmd, shell=True, check=True)
        logging.info("重启命令已发送，等待设备重启...")
        time.sleep(60)  # 等待1分钟让设备完成重启
        if wait_for_device_after_reboot():
            logging.info("设备重启完成")
            if unlock_device():
                logging.info("设备解锁成功")
            else:
                logging.error("设备解锁失败")
        else:
            logging.error("等待设备重启超时")
    except subprocess.CalledProcessError as e:
        logging.error(f"重启设备时出错: {e}")

def wait_for_device_after_reboot(max_wait_time=300, check_interval=10):
    """
    等待设备在重启后重新连接
    
    :param max_wait_time: 最大等待时间（秒）
    :param check_interval: 检查间隔（秒）
    :return: 如果设备成功连接返回 True，否则返回 False
    """
    logging.info(f"等待设备重新连接，最大等待时间: {max_wait_time}秒")
    start_time = time.time()
    
    while time.time() - start_time < max_wait_time:
        if reconnect_adb(ADB_DEVICE):
            logging.info("设备已重新连接")
            return True
        time.sleep(check_interval)
    
    logging.error(f"等待设备重新连接超时（{max_wait_time}秒）")
    return False

@ensure_adb_connection
def unlock_device():
    """解锁设备屏幕"""
    logging.info("正在解锁设备屏幕...")
    # 模拟从屏幕底部向上滑动的操作, 屏幕分辨率1080x1920
    cmd = f"adb -s {ADB_DEVICE} shell input swipe 540 1800 540 800"
    try:
        subprocess.run(cmd, shell=True, check=True)
        logging.info("设备屏幕解锁成功")
        time.sleep(3)  # 等待解锁动画完成
    except subprocess.CalledProcessError as e:
        logging.error(f"解锁设备屏幕时出错: {e}")
        return False
    return True

@ensure_adb_connection
def turn_off_screen():
    """关闭手机屏幕函数"""
    cmd = f"adb -s {ADB_DEVICE} shell CLASSPATH=/mnt/sdcard/Documents/DisplayToggle.dex app_process / DisplayToggle 0"
    try:
        result = subprocess.run(cmd, shell=True, check=False, capture_output=True, text=True)
        if "Display mode: 0" in result.stdout:
            logging.info("成功关闭手机屏幕.")
            return True
        else:
            logging.error(f"关闭手机屏幕失败: {result.stdout}")
            return False
    except Exception as e:
        logging.error(f"执行关闭手机屏幕命令时发生错误: {e}")
        return False

def on_connect(client, userdata, flags, rc, properties=None):
    """MQTT连接成功后的回调函数"""
    logging.info(f"连接成功，返回码: {rc}")
    client.subscribe(MQTT_TOPIC)
    client.subscribe(MQTT_CHECK_TOPIC)

def on_message(client, userdata, msg):
    """接收到MQTT消息后的回调函数"""
    logging.info(f"收到MQTT消息: {msg.topic} {str(msg.payload)}")
    if msg.topic == MQTT_TOPIC:
        if msg.payload == b"UNLOCK":
            control_lock("unlock", client)
        elif msg.payload == b"LOCK":
            control_lock("lock", client)
    elif msg.topic == MQTT_CHECK_TOPIC:
        check_and_publish_status(client)

@ensure_adb_connection
def release_sleep_mode():
    """解除Android设备的睡眠模式"""
    cmd_release_sleep = f"adb -s {ADB_DEVICE} shell input tap {RELEASE_SLEEP_MODE}"
    try:
        subprocess.run(cmd_release_sleep, shell=True, check=True)
        logging.info("执行【スリープモード解除】操作成功.")
        time.sleep(1)  # 等待1秒
    except subprocess.CalledProcessError as e:
        logging.error(f"执行【スリープモード解除】操作失败: {e}")

def check_lock_status():
    """检查门锁状态"""
    release_sleep_mode()
    image = capture_screen()
    pixel = image.getpixel(tuple(map(int, COLOR_CHECK_COORDS.split())))
    logging.info(f"在坐标处检测到颜色: {pixel}")

    def color_matches(color1, color2, tolerance):
        return all(abs(c1 - c2) <= tolerance for c1, c2 in zip(color1[:3], color2[:3]))

    if color_matches(pixel, UNLOCK_COLOR, COLOR_TOLERANCE):
        logging.info("检测到未锁定状态（红色）.")
        return "unlocked"
    elif color_matches(pixel, LOCKED_COLOR, COLOR_TOLERANCE):
        logging.info("检测到锁定状态（绿色）.")
        return "locked"
    elif color_matches(pixel, UNLINKED_COLOR, COLOR_TOLERANCE):
        logging.warning("检测到未连接状态（灰色）.")
        return "unlinked"
    else:
        logging.warning(f"无法匹配颜色: {pixel}")
        return "unknown"

@ensure_adb_connection
def capture_screen():
    """捕获Android设备屏幕截图"""
    cmd = f"adb -s {ADB_DEVICE} exec-out screencap -p"
    result = subprocess.run(cmd, shell=True, capture_output=True)
    return Image.open(io.BytesIO(result.stdout))

@ensure_adb_connection
def control_lock(action, client, retry=2):
    """控制门锁的锁定或解锁"""
    release_sleep_mode()

    coords = UNLOCK_COORDS if action == "unlock" else LOCK_COORDS
    cmd = f"adb -s {ADB_DEVICE} shell input tap {coords}"
    try:
        subprocess.run(cmd, shell=True, check=True)
        logging.info(f"执行{action}操作")
        time.sleep(3)  # 等待操作完成
        
        status = check_lock_status()
        if status == "unlinked":
            logging.warning("门锁未连接,无法执行操作!")
            client.publish(MQTT_STATE_TOPIC, "UNLINKED")
        elif (action == "unlock" and status == "unlocked") or (action == "lock" and status == "locked"):
            logging.info(f"{action}操作成功.")
            client.publish(MQTT_STATE_TOPIC, status.upper())
        elif retry > 0:
            logging.warning(f"{action}操作未成功,重试...")
            save_screenshot(action, True)  # 保存屏幕截图
            retry -= 1
            control_lock(action, client, retry)  # 重试
        else:
            logging.error(f"{action}操作失败!")
            client.publish(MQTT_STATE_TOPIC, "UNKNOWN")
            save_screenshot(action)  # 保存屏幕截图
    except subprocess.CalledProcessError as e:
        logging.error(f"执行{action}操作失败: {e}")
        client.publish(MQTT_STATE_TOPIC, "ERROR")
        save_screenshot(action)  # 保存屏幕截图

@ensure_adb_connection
def save_screenshot(action, retry=False):
    """保存屏幕截图（用于调试）"""
    logging.info("开始保存屏幕截图...")
    current_time = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{'@retry_' if retry else ''}{action}_{current_time}.png"
    file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'errshot', filename)
    
    cmd = f"adb -s {ADB_DEVICE} exec-out screencap -p > {file_path}"
    try:
        subprocess.run(cmd, shell=True, check=True)
        logging.info(f"屏幕截图已保存: {filename}")
    except subprocess.CalledProcessError as e:
        logging.error(f"保存屏幕截图失败: {e}")

def if_app_is_not_running_then_open_it():
    """如果APP没有在运行则启动它"""
    if not is_app_running():
        logging.info("应用未运行，正在启动应用...")
        launch_app()

@ensure_adb_connection
def is_app_running():
    """检查指定的应用是否在前台运行"""
    cmd = "adb shell \"su -c 'dumpsys activity activities | grep mResumedActivity'\""
    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode('utf-8')
        return "com.alpha.lockapp/.MainActivity" in output
    except subprocess.CalledProcessError:
        logging.error("检查应用状态时出错!")
        return False

@ensure_adb_connection
def launch_app():
    """启动指定的应用并点击OK按钮"""
    cmd = "adb shell am start -n com.alpha.lockapp/.MainActivity"
    try:
        subprocess.run(cmd, shell=True, check=True)
        logging.info("应用启动命令已执行...")
        time.sleep(5)  # 等待5秒让应用启动
        
        # 点击OK按钮
        cmd_click = f"adb -s {ADB_DEVICE} shell input tap {LAUNCH_OK_BUTTON}"
        subprocess.run(cmd_click, shell=True, check=True)
        logging.info("已点击OK按钮. 等待15秒与门锁连接...")
        time.sleep(15)  # 等待15秒让应用与门锁连接
        logging.info("连接成功.")
    except subprocess.CalledProcessError as e:
        logging.error(f"启动应用或点击OK按钮失败: {e}")

def check_and_publish_status(client):
    """检查锁状态并发布到MQTT"""
    if_app_is_not_running_then_open_it()

    status = check_lock_status()
    if status == "unlocked":
        logging.info("检查结果: 门锁已解锁")
        client.publish(MQTT_STATE_TOPIC, "UNLOCKED")
    elif status == "locked":
        logging.info("检查结果: 门锁已锁定")
        client.publish(MQTT_STATE_TOPIC, "LOCKED")
    elif status == "unlinked":
        logging.warning("检查结果: 门锁未连接")
        client.publish(MQTT_STATE_TOPIC, "UNLINKED")
    else:
        logging.warning("检查结果: 无法确定门锁状态")
        client.publish(MQTT_STATE_TOPIC, "UNKNOWN")
    return status

def periodic_status_check():
    """定期检查门锁状态的函数"""
    current_time = datetime.datetime.now().time()
    # 在特定时间段内检查门锁状态
    if datetime.time(START_HOUR, 0) <= current_time <= datetime.time(STOP_HOUR, 0):
        check_and_publish_status(mqtt_client)

def schedule_daily_reboot():
    """安排每天凌晨3点重启设备"""
    schedule.every().day.at("03:00").do(daily_reboot_and_initialize)

def daily_reboot_and_initialize():
    """每日重启和初始化流程"""
    reboot_android_device()
    retry_count = 3
    while retry_count > 0:
        if initialize_system():
            logging.info("每日重启和初始化完成")
            return
        else:
            logging.error(f"初始化失败，剩余重试次数: {retry_count-1}")
            retry_count -= 1
            time.sleep(60)  # 等待1分钟后重试
    logging.critical("每日重启后初始化失败，请手动检查设备状态")
    if not unlock_device():
        logging.error("无法解锁设备屏幕!")
        return False

def initialize_system():
    """系统初始化"""
    if not check_adb_connection():
        logging.error("无法连接到Android设备, 请检查网络连接和ADB设置!")
        return False
    time.sleep(10)

    # 如果程序没有在运行则启动
    if_app_is_not_running_then_open_it()
    time.sleep(10)
    # 关闭屏幕
    turn_off_screen()
    return True

def schedule_tasks():
    """安排所有定时任务"""
    schedule.every().day.at(REBOOT_TIME).do(daily_reboot_and_initialize)
    schedule.every(CHECK_INTERVAL).minutes.do(periodic_status_check)

def run_pending_and_get_next_run():
    """检查到下一个定时任务的时长"""
    schedule.run_pending()
    return schedule.idle_seconds()

# 主程序
if __name__ == "__main__":
    # 设置日志
    setup_logging()
    logging.info("智能门锁程序启动...")
    
    # 启动定时任务
    schedule_tasks()

    if not initialize_system():
        logging.error("初始化失败，程序退出")
        exit(1)

    # MQTT
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    try:
        # MQTT连接
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)        
        # 启动MQTT客户端循环
        mqtt_client.loop_start()
        
        # 运行定时任务
        while True:
            # 运行待执行的任务并获取下一个任务的等待时间
            wait_time = run_pending_and_get_next_run()
            # 如果下一个任务在30秒以上，稍微休眠长一点
            if wait_time > 30:
                time.sleep(30)
            elif wait_time > 0:
                time.sleep(wait_time)
            else:
                # 如果没有等待时间，仍然短暂休眠以避免CPU过载
                time.sleep(1)
    except Exception as e:
        logging.error(f"运行时错误: {e}")
        exit(1)