
import pika
import time
import cv2
import pickle  # To serialize frames
import struct  # To send the size of the frame
from multiprocessing import Process, current_process
import logging
import datetime
import threading
import requests


# Function to send logs to RabbitMQ
def send_log_to_rabbitmq(log_message):
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host='rabbitmq', heartbeat=600))
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
    current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    message_data = {
        "log_level" : "INFO",
        "Event_Type":"Start threads for send frames",
        "Message":message,
        "datetime":current_time,

    }
    send_log_to_rabbitmq(message_data)

def log_error(message):
    logging.info(message)
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message_data = {
        "log_level" : "ERROR",
        "Event_Type":"Start threads for send frames",
        "Message":message,
        "datetime" : current_time,

    }
    send_log_to_rabbitmq(message_data)    

def log_exception(message):
    logging.error(message)
    current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    message_data = {
        "log_level" : "EXCEPTION",
        "Event_Type":"Start threads for send frames",
        "Message":message,
        "datetime" : current_time,

    }
    send_log_to_rabbitmq(message_data)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Dictionary to keep track of camera processes
camera_processes = {}

def setup_rabbitmq_connection(queue_name, rabbitmq_host, retries=5, retry_delay=5):
    """
    Set up a RabbitMQ connection and declare the queue.
    """
    for attempt in range(retries):
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbitmq_host, heartbeat=600))
            channel = connection.channel()
            channel.queue_declare(queue=queue_name)
            log_info(f"Connected to RabbitMQ at {rabbitmq_host}")
            return connection, channel
        except pika.exceptions.AMQPConnectionError as e:
            log_error(f"RabbitMQ connection failed (attempt {attempt+1}/{retries}): {e}")
            time.sleep(retry_delay)
    raise log_exception(f"Could not connect to RabbitMQ after {retries} attempts")

def process_video(camera_url, camera_id, camera_ip, objectlist, user_id, credit_id, rabbitmq_host, queue_name, frame_interval, retry_limit=50):
    """
    Process the video stream and send frames to RabbitMQ.
    """
    retry_count = 0
    while retry_count < retry_limit:
        cap = cv2.VideoCapture(camera_url)

        if not cap.isOpened():
            log_error(f"Error: Could not open video stream from {camera_url}")
            retry_count += 1
            time.sleep(5)
            continue

        log_info(f"Processing video stream from {camera_id}")
        connection, channel = setup_rabbitmq_connection(queue_name, rabbitmq_host)

        frame_count = 0
        last_frame_time = time.time()

        try:
            while cap.isOpened():
                ret, frame = cap.read()

                if not ret:
                    if time.time() - last_frame_time > 5:
                        log_error(f"No frame received for 5 seconds from {camera_id}, restarting...")
                        break
                    continue

                last_frame_time = time.time()

                frame_count += 1
                if frame_count % frame_interval != 0:
                    continue

                frame_count = 0
                current_datetime = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                frame_data = {
                    "camera_id": camera_id,
                    "camera_ip": camera_ip,
                    "object_list": objectlist,
                    "datetime": current_datetime,
                    "frame": frame,
                    "user_id": user_id,
                    "credit_id": credit_id,
                }
                serialized_frame = pickle.dumps(frame_data)

                channel.basic_publish(
                    exchange="",
                    routing_key=queue_name,
                    body=serialized_frame
                )
                log_info(f"Sent a frame from camera {camera_id} (Process ID: {current_process().pid})")

        except Exception as e:
            log_exception(f"An error occurred in camera {camera_id}: {e}")
        finally:
            cap.release()
            connection.close()
            log_info(f"Camera {camera_id}: Video processing complete. RabbitMQ connection closed.")
            retry_count += 1
            if retry_count >= retry_limit:
                log_error(f"Failed to process video stream after {retry_count} retries.")
                break

# Dictionary to keep track of camera URLs by their IDs
camera_urls = {}
user_ids ={}
credit_ids = {}

def start_camera_process(camera_url, camera_id, camera_ip, objectlist, user_id, credit_id, rabbitmq_host, queue_name="all_frames", frame_interval=25):
    """
    Start a separate process for each camera.
    """
    process = Process(target=process_video, args=(camera_url, camera_id, camera_ip, objectlist, user_id, credit_id, rabbitmq_host, queue_name, frame_interval))
    process.start()
    camera_processes[camera_id] = process  # Store process in the dictionary
    camera_urls[camera_id] = camera_url  # Store the camera URL for later use
    user_ids[camera_id] = user_id   # Store the user
    credit_ids[camera_id] = credit_id  # Store the credit ID for later use
    log_info(f"Started a new process for camera {camera_id} (Process ID: {process.pid})")
    return process


def stop_camera_process(camera_id):
    """
    Stop the camera process if it's running.
    """
    process = camera_processes.get(camera_id)
    if process and process.is_alive():
        log_info(f"Stopping process for camera {camera_id}")
        process.terminate()
        process.join()
        log_info(f"Camera {camera_id}: Process stopped.")
        del camera_processes[camera_id]  # Remove from dictionary
    else:
        log_error(f"No active process found for camera {camera_id}")


camera_status = {}

def monitor_camera_processes(rabbitmq_host="rabbitmq", queue_name="all_frames", frame_interval=15):
    while True:
        for camera_id, process in list(camera_processes.items()):
            # Check if camera status is set to False; if so, stop and remove from monitoring
            if not camera_status.get(camera_id, True):
                if process.is_alive():
                    log_info(f"Stopping camera process for {camera_id} as status is set to False.")
                    stop_camera_process(camera_id)
                continue  # Skip this camera for now since it shouldn't be monitored

            # If process has stopped and status is True, restart it
            if not process.is_alive():
                log_info(f"Process for camera {camera_id} has stopped unexpectedly. Attempting to restart...")

                # Fetch the camera URL from the stored dictionary
                if camera_id in camera_urls:
                    camera_url = camera_urls[camera_id]
                    user_id = user_ids.get(camera_id)
                    credit_id = credit_ids.get(camera_id)
                    start_camera_process(camera_url, camera_id, user_id, credit_id, rabbitmq_host, queue_name, frame_interval)
                else:
                    log_error(f"No URL found for camera {camera_id}, unable to restart.")
                    
        time.sleep(25)  # Check every 25 seconds

def fetch_camera_data_from_queue(queue_name, rabbitmq_host="rabbitmq"):

    BaseUrl = "https://vmsapi3.ajeevi.in"

    url = f'{BaseUrl}/api/VideoAnalytic/GetAllActive'
    #datas=[]
    try:
        # Sending a GET request to the URL
        response = requests.get(url)
        
        # Check if the request was successful
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)

        # Parsing the response as JSON (if the API returns JSON)
        datas = response.json()

        print("Camera details:" ,datas)

    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
    except requests.exceptions.ConnectionError as conn_err:
        print(f"Error connecting to {url}: {conn_err}")
    except requests.exceptions.Timeout as timeout_err:
        print(f"Timeout error: {timeout_err}")
    except requests.exceptions.RequestException as req_err:
        print(f"An error occurred: {req_err}")
    except ValueError as json_err:
        print(f"JSON decoding failed: {json_err}")
    
    for data in datas:
        print(data)
        print(data["cameraId"],data["cameraIP"],data["rtspUrl"],data["objectList"])
        camera_id=data["cameraId"]
        camera_ip=data["cameraIP"]
        camera_url=data["rtspUrl"]   # have status true
        objectlist=data["ObjectList"]
        #print("First object list : ",objectlist)
        #start_camera_process(camera_url, camera_id,camera_ip, objectlist, rabbitmq_host)


    """
    Fetch camera ID and RTSP URL from RabbitMQ queue and manage the camera processes.
    """
    connection, channel = setup_rabbitmq_connection(queue_name, rabbitmq_host)
    
    def callback(ch, method, properties, body):
        try:
            camera_data = pickle.loads(body)
            
            camera_id = camera_data.get("CameraId")
            camera_ip = camera_data.get("CameraIp")
            running_status = camera_data.get("Running").upper()
            objectlist = camera_data.get("ObjectList")
            camera_url = camera_data.get("CameraUrl")
            user_id = camera_data.get("UserId")
            credit_id = camera_data.get("CreditId")
            #print("Second object list : ", objectlist)

            if running_status == "TRUE":
                camera_status[camera_id] = True
                # Start process if not already running
                if camera_id not in camera_processes or not camera_processes[camera_id].is_alive():
                    log_info(f"Starting camera process for {camera_id}.")
                    start_camera_process(camera_url, camera_id,camera_ip, objectlist, user_id, credit_id, rabbitmq_host)
            else:
                # Set status to False and stop process if running
                camera_status[camera_id] = False
                if camera_id in camera_processes and camera_processes[camera_id].is_alive():
                    log_info(f"Stopping camera process for {camera_id}.")
                    stop_camera_process(camera_id)

        except Exception as e:
            log_exception(f"Failed to process message from RabbitMQ: {e}")

    # Start consuming the queue
    channel.basic_consume(queue=queue_name, on_message_callback=callback, auto_ack=True)
    log_info(f"Waiting for camera data from queue {queue_name}...")
    channel.start_consuming()

if __name__ == "__main__":
    # Start the monitor thread
    monitor_thread = threading.Thread(target=monitor_camera_processes, daemon=True)
    monitor_thread.start()
    
    # Fetch camera ID and RTSP URL from RabbitMQ queue 'details'
    fetch_camera_data_from_queue(queue_name="camera_details")
