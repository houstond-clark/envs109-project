#!/usr/bin/env python3
import serial
import math
import time
import json
import sys
import signal
import requests
# For dealing with fetching run configurations
import requests
from urllib3.exceptions import InsecureRequestWarning

# Suppress only the single warning from urllib3 needed.
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

from sense_hat import SenseHat
from awscrt import io, mqtt
from awsiot import mqtt_connection_builder

# Set some default values
senseHat = None
airSerial = None
mqtt_connection = None
vcgm = None
sensorId = None
dataPoints = 720 
dataCounter = 0

# Topic base
RUN="default"
CLIENT_ID = "control"
try:
    response = requests.get("https://rec.home/AQ/runs.json", verify=False)
    jsonresp = json.loads(response.text)
    RUN = jsonresp[CLIENT_ID]
    print(f"Set run to {RUN}")
except Exception:
    print(Exception.with_traceback())
    print("Could not set the run value..")
    pass

TOPIC_BASE = f"aq/{CLIENT_ID}"
# The "run" name for this run of the data gathering
TOPIC = f"{TOPIC_BASE}/{RUN}"

# IoT Variables
ENDPOINT = "a1qecpjelyfwp0-ats.iot.us-east-1.amazonaws.com"
PATH_TO_CERT = "/home/pi/aq/certs/certificate.pem.crt"
PATH_TO_KEY = "/home/pi/aq/certs/private.pem.key"
PATH_TO_ROOT = "/home/pi/aq/certs/AmazonRootCA1.pem"

# MQTT startup
try:
    print("Starting MQTT process")
    event_loop_group = io.EventLoopGroup(1)
    host_resolver = io.DefaultHostResolver(event_loop_group)
    client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)
    mqtt_connection = mqtt_connection_builder.mtls_from_path(
            endpoint=ENDPOINT,
            cert_filepath=PATH_TO_CERT,
            pri_key_filepath=PATH_TO_KEY,
            client_bootstrap=client_bootstrap,
            ca_filepath=PATH_TO_ROOT,
            client_id=CLIENT_ID,
            clean_session=False,
            keep_alive_secs=6)
    # Make the connect() call
    connect_future = mqtt_connection.connect()
    # Future.result() waits until a result is available
    connect_future.result()
    print("Connected!")
except Exception:
    print("Problem connecting, aborting.")
    print(Exception.with_traceback())
    cleanup()

# Initial sensor setup
try:
    senseHat = SenseHat()
    senseHat.low_light = True
except Exception:
    print("Problem loading SenseHat, aborting.")
    cleanup()

try:
    airSerial = serial.Serial("/dev/ttyUSB0")
except Exception:
    print("Problem connectiong to SDS011, aborting.")
    cleanup()


# Read from AQ serial, returns PM 2.5 and PM 10
def getAQ(serial):
    data = []
    for index in range(0, 10):
        serIn = airSerial.read()
        data.append(serIn)

    pmTwoFive = int.from_bytes(b''.join(data[2:4]), byteorder='little') / 10
    pmTen = int.from_bytes(b''.join(data[4:6]), byteorder='little') / 10

    return [pmTwoFive, pmTen]

def getHumidity(senseHat):
    return senseHat.get_humidity()

def getPressure(senseHat):
    return senseHat.get_pressure()

def cleanup():
    senseHat.clear()
    sys.exit()

def sendIt(data, count, max):
    if count > max:
        print("Max count exceeded, we're done here.")
        cleanup()
    message = data
    message["timestamp"] = time.time()
    message["sensor_id"] = CLIENT_ID
    message["num"] = count
    message["max"] = max
    message["run"] = TOPIC
    try:
        mqtt_connection.publish(
                topic = TOPIC,
                payload = json.dumps(message),
                qos = mqtt.QoS.AT_LEAST_ONCE)
    except Exception:
        print("Unable to publish message: ", json.dumps(message))

def showIt(data, hat, count, max):
    hat.clear()
    percentToLight = count / max
    pixelCount = 64
    pixelsToLight = pixelCount * percentToLight

    rowsToFill = math.floor(pixelsToLight / 8)
    remainsToLight = int(pixelsToLight % 8)


    print(f"count/max: {count}/{max}, percent: {percentToLight}, rows: {rowsToFill}, remains: {remainsToLight}")
    for row in range(rowsToFill):
        for col in range(8):
            hat.set_pixel(row, col, (128, 128, 128))

    for col in range(remainsToLight):
        hat.set_pixel(rowsToFill, col, (128, 128, 128))

    print(data)

def main():
    dataCounter = 0
    while dataCounter < dataPoints:
        dataCounter = dataCounter + 1
        print(f"{dataCounter} of {dataPoints}")
        try:
            pm25, pm10 = getAQ(airSerial)
            pressure = getPressure(senseHat)
            humidity = getHumidity(senseHat)
            data = {
                    "pm25": pm25,
                    "pm10": pm10,
                    "pressure": pressure,
                    "humidity": humidity
                    }
            sendIt(data, dataCounter, dataPoints)
            showIt(data, senseHat, dataCounter, dataPoints)
            time.sleep(30)
        except KeyboardInterrupt:
            print("Manual kill")
            cleanup()
signal.signal(signal.SIGTERM, cleanup)

main()
