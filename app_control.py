import paho.mqtt.client as mqtt
import subprocess
import time

# MQTT设置
MQTT_BROKER = "192.168.11.5"
MQTT_PORT = 21883
MQTT_TOPIC = "home/doorlock/set"

# ADB设置
ADB_DEVICE = "192.168.11.135:5555"  # 使用Android设备的IP地址和端口

# 点击坐标（根据您的应用界面调整）
UNLOCK_COORDS = "750 1200"        # 解锁按钮的x y坐标
LOCK_COORDS = "330 1200"          # 锁定按钮的x y坐标
RELEASE_SLEEP_MODE = "530 1440"   # 解除睡眠按钮的x y坐标

def on_connect(client, userdata, flags, rc):
    print("Connected with result code "+str(rc))
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    print(f"Received message: {msg.topic} {str(msg.payload)}")
    if msg.payload == b"UNLOCK":
        control_lock("unlock")
    elif msg.payload == b"LOCK":
        control_lock("lock")

def control_lock(action):
    # 先点击【スリープモード解除】
    cmd_release_sleep = f"adb -s {ADB_DEVICE} shell input tap {RELEASE_SLEEP_MODE}"
    try:
        subprocess.run(cmd_release_sleep, shell=True, check=True)
        print(f"执行【スリープモード解除】操作成功")
        # 发送状态更新到Home Assistant
    except subprocess.CalledProcessError as e:
        print(f"执行【スリープモード解除】操作失败: {e}")
    time.sleep(1)

    if action == "unlock":
        coords = UNLOCK_COORDS
    else:
        coords = LOCK_COORDS
    
    cmd = f"adb -s {ADB_DEVICE} shell input tap {coords}"
    try:
        subprocess.run(cmd, shell=True, check=True)
        print(f"执行{action}操作成功")
        # 发送状态更新到Home Assistant
        client.publish("home/doorlock/state", "UNLOCKED" if action == "unlock" else "LOCKED")
    except subprocess.CalledProcessError as e:
        print(f"执行{action}操作失败: {e}")

def check_adb_connection():
    cmd = f"adb connect {ADB_DEVICE}"
    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        print(f"ADB连接结果: {result.stdout.strip()}")
        return "connected" in result.stdout.lower()
    except subprocess.CalledProcessError as e:
        print(f"ADB连接失败: {e}")
        return False

# 主程序
if __name__ == "__main__":
    # 首先检查并确保ADB连接
    if not check_adb_connection():
        print("无法连接到Android设备，请检查网络连接和ADB设置")
        exit(1)

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except Exception as e:
        print(f"MQTT连接失败: {e}")
        exit(1)