
import pika
import os
import pickle  # To deserialize and serialize frames
import struct  # To handle frame size unpacking
from ultralytics import YOLO
import datetime
import cv2
import logging
import time
import requests
import math

# List of YOLO object class names
Object_list = ['Person', 'Bicycle', 'Car', 'Motorcycle', 'Airplane', 'Bus', 'Train', 'Truck', 'Boat', 'Traffic Light', 'Fire Hydrant', 
               'Stop Sign', 'Parking Meter', 'Bench', 'Bird', 'Cat', 'Dog', 'Horse', 'Sheep', 'Cow', 'Elephant', 'Bear', 'Zebra', 
               'Giraffe', 'Backpack', 'Umbrella', 'Handbag', 'Tie', 'Suitcase', 'Frisbee', 'Skis', 'Snowboard', 'Sports Ball', 'Kite', 
               'Baseball Bat', 'Baseball Glove', 'Skateboard', 'Surfboard', 'Tennis Racket', 'Bottle', 'Wine Glass', 'Cup', 'Fork', 
               'Knife', 'Spoon', 'Bowl', 'Banana', 'Apple', 'Sandwich', 'Orange', 'Broccoli', 'Carrot', 'Hot Dog', 'Pizza', 'Donut', 
               'Cake', 'Chair', 'Couch', 'Potted Plant', 'Bed', 'Dining Table', 'Toilet', 'TV', 'Laptop', 'Mouse', 'Remote', 
               'Keyboard', 'Cell Phone', 'Microwave', 'Oven', 'Toaster', 'Sink', 'Refrigerator', 'Book', 'Clock', 'Vase', 
               'Scissors', 'Teddy Bear', 'Hair Drier', 'Toothbrush']

# Cattle for detection
CATTLE_CLASSES = ["cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"]

# Load the YOLO model
model = YOLO("yolov8m.pt")
seat_belt_model=YOLO("belt_mobile_65v8s_best.pt")
helmet_model = YOLO("hemletYoloV8_100epochs.pt")


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
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message_data = {
        "log_level" : "INFO",
        "Event_Type":"Start threads for send frames",
        "Message":message,
        "datetime" : current_time,

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
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message_data = {
        "log_level" : "EXCEPTION",
        "Event_Type":"Start threads for send frames",
        "Message":message,
        "datetime" : current_time,

    }
    send_log_to_rabbitmq(message_data)


# Directory to save frames 
vehicle_frame = "vehicle_frame"
os.makedirs(vehicle_frame, exist_ok=True)


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


def publish_to_queue(camera_id, frame, processed_channel,processed_queue_name):
    """Publish processed data to RabbitMQ."""
    print("publish")
    processed_frame_data = {
        "camera_id": camera_id,
        "frame": frame
    }
    serialized_frame = pickle.dumps(processed_frame_data)
    processed_channel.basic_publish(exchange="", routing_key=processed_queue_name, body=serialized_frame)


def process_cattle(frame, results):
    """Process detections for 'Cattle on Road'."""
    cattle_detected = 0
    for result in results.boxes.data.tolist():
        x1, y1, x2, y2, cattle_score, cattle_id = result
        label = Object_list[cattle_id].lower()
        if label in CATTLE_CLASSES and cattle_score > 0.5:
            # Draw bounding box
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
            cattle_detected += 1

    return frame, cattle_detected


def process_frame(ch, method, properties, body, processed_channel,processed_queue_name, rabbitmq_host):
    """
    Callback function to process the received frames from RabbitMQ.

    Args:
        ch, method, properties: RabbitMQ parameters.
        body: The serialized frame data received from the queue.
        processed_channel: RabbitMQ channel for sending processed frames.
    """
    if not processed_channel.is_open:
        log_error("Receiver channel is closed. Attempting to reconnect.")
        processed_connection, processed_channel = setup_rabbitmq_connection(processed_queue_name, rabbitmq_host)
    try:
        # Deserialize the frame and metadata
        frame_data = pickle.loads(body)

        camera_id = frame_data["camera_id"]
        camera_ip = frame_data["camera_ip"]
        object_list = frame_data["object_list"]
        datetime = frame_data["datetime"]
        frame = frame_data["frame"]
        user_id = frame_data["user_id"]
        credit_id = frame_data["credit_id"]
        #print("Frame data :", frame_data)
        # Detect and classify objects in the frame
        detected_object = {}
        flag = 0
        object_for_detection = object_list

        if not object_for_detection:
            return frame, detected_object, flag
        
        results = model(frame, verbose=False)[0]
        for result in results.boxes.data.tolist():
            x1, y1, x2, y2, score, id = result
            label = results.names[int(id)]
            print("main label :", label)
            print("score :", score)
            if label in object_for_detection and score > 0.5:
                # Serialize the frame and send it to the 'processed_frames' queue
                flag = 1
                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                detected_object[label] = detected_object.get(label, 0) + 1
                log_info(f"Detected object with label ans camera_id : {camera_id}")

        if "Cattle on road" in object_for_detection:
            #print("Cattle on road")
            frame, cattle_count = process_cattle(frame, results)
            if cattle_count > 0:
                flag = 1
                detected_object["Cattle"] = cattle_count  
                log_info(f"Cattle detected successfully for camera_id : {camera_id}")

        # Specific Rules: Without Seat Belt
        if "Without Seat belt" in object_for_detection:
            #print("Without Seat belt")
            results2 = seat_belt_model(frame,verbose=False)[0]
            for result in results2.boxes.data.tolist():
                x1, y1, x2, y2, seat_score, seat_id = result
                label_seat = results2.names[seat_id]
                if label_seat == "no-seatbelt" and seat_score > .5:
                    flag = 1
                    publish_to_queue(camera_id, frame, processed_channel,processed_queue_name="detected_vehicle")
                    cv2.rectangle(frame, (int(x1), int(y1)), (int(x2)), (0, 255, 0), 2)
                    detected_object["Without Seat belt"] = detected_object.get("Without Seat belt", 0) + 1  
                    log_info(f"Seat belt detected successfully for camera_id : {camera_id}")  


        # Specific Rules: Without Helmet
        if "Without Helmet" in object_for_detection:
            #print("Without Helmet")
            results3 = helmet_model(frame,verbose=False)[0]  # Detect HEAD using helmet model
            head_boxes = []
            
            # Collect all HEAD detections
            for result3 in results3.boxes.data.tolist():
                hx1, hy1, hx2, hy2, helmet_score, helmet_id = result3
                if results3.names[helmet_id] == "head" and helmet_score > .5:
                    head_boxes.append((hx1, hy1, hx2, hy2))
                    log_info(f"Head detected with camera_id :{camera_id}")
            
            # Check for motorcycles below detected HEADs
            results4 = model(frame)  # General object detection
            for result4 in results4:
                mx1, my1, mx2, my2, motor_score, motor_id = result4
                mlabel = results4.names[int(motor_id)]
                if mlabel == "motorcycle" and motor_score > 0.5:
                    # Check if any HEAD is above this motorcycle
                    head_center_x = (hx1 + hx2) // 2
                    head_center_y = (hy1 + hy2) // 2
                    
                    # Calculate motorcycle bounding box center
                    moto_center_x = (mx1 + mx2) // 2
                    moto_center_y = (my1 + my2) // 2
                    
                    # Calculate Euclidean distance
                    distance = math.sqrt((head_center_x - moto_center_x)**2 + (head_center_y - moto_center_y)**2)
                    
                    # Check if the distance is within the threshold (e.g., 50 pixels)
                    if distance < 100:
                        # Publish to queue and annotate frame
                        flag = 1
                        publish_to_queue(camera_id, frame, processed_channel,processed_queue_name="detected_vehicle")
                        detected_object["Without Helmet"] = detected_object.get("Without Helmet", 0) + 1
                        color = (0, 255, 0)
                        cv2.rectangle(frame, (int(mx1), int(my1)), (int(mx2), int(my2)), color, 2)
                        cv2.rectangle(frame, (int(hx1), int(hy1)), (int(hx2), int(hy2)), (255, 0, 0), 2)
                        log_info(f"Motorcycle detected with camera_id :{camera_id}")                       
        # Serialize the processed license plate frame
        #print("Detected object :", detected_object)
        #print("object :", object_for_detection)
        if detected_object:
            image_info = {
                "Event_Type":"Analytics",
                "CameraId": camera_id,
                'CameraIp': camera_ip,
                'Datetime': datetime,
                'Image': frame,
                'Object': detected_object,
                "UserId": user_id,
                "CreditId": credit_id,
            }
            serialized_frame = pickle.dumps(image_info)
            # Send the processed frame to the 'processed_frames' queue
            processed_channel.basic_publish(
                exchange="",
                routing_key="video_analytics",
                body=serialized_frame
            )
            log_info("Object detected successfully")
    except Exception as e:
        log_exception(f"Error processing frame: {e}")
        processed_connection, processed_channel = setup_rabbitmq_connection(processed_queue_name, rabbitmq_host)

def main(queue_name="all_frames", processed_queue_name="video_analytics", rabbitmq_host="rabbitmq"):
    """
    Main function to set up RabbitMQ connections for receiving and sending frames.

    Args:
        queue_name (str): The RabbitMQ queue to consume frames from. Defaults to 'video_frames'.
        processed_queue_name (str): The RabbitMQ queue to send processed frames to. Defaults to 'processed_frames'.
    """
    # Set up RabbitMQ connection and channel for receiving frames
    receiver_connection, receiver_channel = setup_rabbitmq_connection(queue_name,rabbitmq_host)

    # Set up RabbitMQ connection and channel for sending processed frames
    processed_connection, processed_channel = setup_rabbitmq_connection(processed_queue_name, rabbitmq_host)

    # ---------------------------------------------------
    if not receiver_channel.is_open:
        log_error("Receiver channel is closed. Attempting to reconnect.")
        receiver_connection, receiver_channel = setup_rabbitmq_connection(queue_name, rabbitmq_host)
    if not processed_channel.is_open:
        log_error("Receiver channel is closed. Attempting to reconnect.")
        processed_connection, processed_channel = setup_rabbitmq_connection(processed_queue_name, rabbitmq_host)    

    while True:
        try:
            if not receiver_channel.is_open:
                log_error("Receiver channel is closed. Attempting to reconnect.")
                time.sleep(25)
                receiver_connection, receiver_channel = setup_rabbitmq_connection(queue_name, rabbitmq_host)
            if not processed_channel.is_open:
                log_error("Receiver channel is closed. Attempting to reconnect.")
                time.sleep(25)
                processed_connection, processed_channel = setup_rabbitmq_connection(processed_queue_name, rabbitmq_host)
            
            receiver_channel.basic_consume(
                queue=queue_name, 
                on_message_callback=lambda ch, method, properties, body: process_frame(
                    ch, method, properties, body, processed_channel,processed_queue_name, rabbitmq_host
                ),
                auto_ack=True
            )
            log_info("Waiting for video frames...")
            receiver_channel.start_consuming()
        
        except pika.exceptions.ConnectionClosedByBroker as e:
            log_error("Connection closed by broker, reconnecting...")
            time.sleep(25)
            receiver_connection, receiver_channel = setup_rabbitmq_connection(queue_name, rabbitmq_host)
            processed_connection, processed_channel = setup_rabbitmq_connection(processed_queue_name, rabbitmq_host)
        except Exception as e:
            log_exception(f"Unexpected error: {e}")
            time.sleep(25)
            continue 

if __name__ == "__main__":
    # Start the receiver and sender
    main()
