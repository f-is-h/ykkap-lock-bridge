# Smart Door Lock Control

This project aims to convert a YKK AP electric lock with app control capabilities into a smart lock that can be controlled via iPhone's Home app, integrating it with Home Assistant and MQTT.

## Table of Contents
- [Project Overview](#project-overview)
- [System Architecture](#system-architecture)
- [Prerequisites](#prerequisites)
- [Installation and Configuration](#installation-and-configuration)
- [Usage](#usage)
- [File Structure](#file-structure)
- [License](#license)

## Project Overview

This project integrates a YKK AP electric lock with Home Assistant using an Android phone as a bridge. It allows for remote control and status monitoring of the door lock through MQTT and HomeKit.

## System Architecture

    ```mermaid
    graph TD
        U((User)) -->|Operate| A[iPhone\n#40;HomeKit#41;]
        A -->|Instruct| C{Home Assistant}
        C -->|Configure| D[MQTT Lock Definition]
        C <-->|Data Exchange| E{MQTT Server}
        F[Docker Container] <-->|Subscribe/Publish| E
        F -->|ADB Commands| G[Android Smartphone]
        G -->|Bluetooth Control| H((YKK AP\nElectric Lock))
        I[Door/Window Sensor] -.->|Optional| C
        I -.->|State Detection| H
    ```

## Prerequisites

- Home Assistant server with HomeKit integration
- MQTT server (Broker address: mqtt://192.168.11.5:21883)
- Android phone with YKK AP's "スマートコントロールキー" app installed and paired with the door lock
- Docker environment for running the control script

## Installation and Configuration

1. Clone this repository to your local machine.
2. Set up the Android phone near the door lock and ensure it's always powered on.
3. Configure the Docker environment:
   - Update the `docker-compose.yml` file with your specific settings:
     ```yaml
     environment:
       - TZ=Asia/Tokyo
       - MQTT_BROKER=192.168.11.5
       - MQTT_PORT=21883
       - ADB_DEVICE=192.168.11.135:5555
       - LOGGING_LEVEL=INFO
     ```
4. Install the necessary Python dependencies as specified in the Docker configuration.
5. Update the `configuration.yaml` file in your Home Assistant setup:
   ```yaml
   input_boolean:
     fake_door_lock_status:
       name: "Virtual Door Lock Status"
       icon: mdi:lock

   lock:
     - platform: template
       name: "Home Door Lock"
       value_template: "{{ is_state('input_boolean.fake_door_lock_status', 'on') }}"
       lock:
         service: script.lock_door
       unlock:
         service: script.unlock_door
   ```
6. Update the `automations.yaml` file in your Home Assistant setup:
   ```yaml
   - id: update-door-lock-status
     alias: Update Door Lock Status
     trigger:
       - platform: mqtt
         topic: home/doorlock/state
     action:
       - choose:
           - conditions:
               - condition: template
                 value_template: "{{ trigger.payload == 'LOCKED' }}"
             sequence:
               - service: input_boolean.turn_on
                 target:
                   entity_id: input_boolean.fake_door_lock_status
           - conditions:
               - condition: template
                 value_template: "{{ trigger.payload == 'UNLOCKED' }}"
             sequence:
               - service: input_boolean.turn_off
                 target:
                   entity_id: input_boolean.fake_door_lock_status
   ```
7. Modify the `app_control.py` script if needed to adjust settings like MQTT topics or check intervals.

## Usage

1. Start the Docker container using the provided `docker-compose.yml` file.
2. The Python script (`app_control.py`) will run automatically, handling communication between MQTT and the door lock.
3. Use your iPhone's Home app to control the door lock.

## File Structure

- `app_control.py`: Main Python script for controlling the door lock
- `docker-compose.yml`: Docker configuration file
- `door-lock-state-flow.mermaid`: Mermaid diagram of the control logic
- `system_overview_diagram.mermaid`: System architecture diagram
- `configuration.yaml`: Home Assistant configuration
- `automations.yaml`: Home Assistant automations
- `screenshot_*.png`: Screenshots of the Android app in different states

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details.