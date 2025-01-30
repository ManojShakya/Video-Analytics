from flask import Flask, request, jsonify , send_from_directory
import os
from flask_cors import CORS
import pickle
import pika
import logging
import datetime
import time
app = Flask(__name__)
CORS(app)


def setup_rabbitmq_connection(queue_name, retries=5, retry_delay=5):
    """
    Set up a RabbitMQ connection and declare the queue.
    """
    rabbitmq_host = "rabbitmq"
    for attempt in range(retries):
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host="rabbitmq"))
            channel = connection.channel()
            channel.queue_declare(queue=queue_name)
            print(f"Connected to RabbitMQ at {rabbitmq_host}")
            return connection, channel
        except pika.exceptions.AMQPConnectionError as e:
            print(f"RabbitMQ connection failed (attempt {attempt+1}/{retries}): {e}")
            time.sleep(retry_delay)
    raise Exception(f"Could not connect to RabbitMQ after {retries} attempts")


def send_log_to_rabbitmq(log_message):
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host='rabbitmq',heartbeat=600))
        channel = connection.channel()
        channel.queue_declare(queue='anpr_logs')  # Declare the queue for logs
        # Serialize the log message as JSON and send it to RabbitMQ
        channel.basic_publish(
            exchange='',
            routing_key='anpr_logs',
            body=pickle.dumps(log_message)
        )
        connection.close()
    except Exception as e:
        print(f"Failed to send log to RabbitMQ: {e}")

# Wrapper functions for logging and sending logs to RabbitMQ
def log_info(message):
    logging.info(message)
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message_data = {
        "log_level" : "INFO",
        "Event_Type":"Send Camera Details in Queue",
        "Message":message,
        "datetime" : current_time,

    }
    send_log_to_rabbitmq(message_data)

def log_error(message):
    logging.info(message)
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message_data = {
        "log_level" : "ERROR",
        "Event_Type":"Send Camera Details in Queue",
        "Message":message,
        "datetime" : current_time,

    }
    send_log_to_rabbitmq(message_data)    

def log_exception(message):
    logging.error(message)
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message_data = {
        "log_level" : "EXCEPTION",
        "Event_Type":"Send Camera Details in Queue",
        "Message":message,
        "datetime" : current_time,

    }
    send_log_to_rabbitmq(message_data)



@app.route('/CameraDetails', methods=['POST'])
def update_camera_details():
    data = request.get_json()

    cameras = data.get("cameras", [])
    if not cameras:
        log_info(f"No cameras provided!")
        return jsonify({"error": "No cameras provided!"}), 400

    for camera in cameras:
        required_fields = ["camera_id", "url", "camera_ip", ]

        if not all(field in camera for field in required_fields):
            log_error(f"Missing required fields in camera details for camera {camera.get('camera_id')}")
            return jsonify({"error": f"Missing required fields in camera details for camera {camera.get('camera_id')}!"}), 400
        camera_id = camera["camera_id"]
        camera_url = camera["url"]
        camera_ip = camera["camera_ip"]
        objectlist = camera.get("objectlist", "[]").lower()
        running = camera.get("running", False).upper()
        user_id = camera["user_id"]
        credit_id = camera["credit_id"]
        # Connect to RabbitMQ
        queue_name='camera_details'

        connection, channel = setup_rabbitmq_connection(queue_name)
        if not channel.is_open:
            log_error("Receiver channel is closed. Attempting to reconnect.")
            connection, channel = setup_rabbitmq_connection(queue_name)

        frame_data = {
                "CameraId":camera_id,
                "CameraIp": camera_ip,
                "CameraUrl":camera_url,
                "ObjectList": objectlist,
                "Running":running,
                "UserId":user_id,
                "CreditId":credit_id 
            }
        serialized_frame = pickle.dumps(frame_data)
        #print("frame_data :", frame_data)

        # Send the frame to the queue
        # if running:
        try:
            channel.basic_publish(
                exchange="",
                routing_key=queue_name,
                body=serialized_frame
            )
            #print(f"Sent camera info{camera_id}")
            log_info(f"Sent camera info camera_id :{camera_id} and camera_ip :{camera_ip}")
        except Exception as e:
            print(f"Failed to publish message: {e}")
            log_exception(f"Failed to publish message: {e} and camera_ip :{camera_ip}")
    log_info("Cameras added/updated successfully!")
    return jsonify({"message": "Cameras added/updated successfully!"}), 201

@app.route('/app/<folder>/<camera_id>/<filename>')
def get_image(folder,camera_id, filename):
    print(camera_id,filename)
    # camera_folder = os.path.join(os.path.join(os.getcwd(), foldername), camera_id)
    # camera_folder = os.path.join(os.getcwd(), foldername, camera_id)
    
    camera_folder = os.path.join(os.path.join(os.getcwd(), folder),camera_id)
    print(camera_folder)
    return send_from_directory(camera_folder, filename)



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5555)
