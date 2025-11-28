# from flask import Flask, request, jsonify, send_from_directory
# from flask_cors import CORS
# import pickle
# import pika
# import logging
# import datetime
# import os
# import time
# # ---------------------------------------------------------
# # App Initialization
# # ---------------------------------------------------------
# app = Flask(__name__)
# CORS(app)

# # ---------------------------------------------------------
# # RabbitMQ Connection Manager (Lazy Persistent Connection)
# # ---------------------------------------------------------

# rabbit_connection = None
# rabbit_channel = None

# def get_rabbitmq_channel():
#     """Create and reuse a persistent RabbitMQ channel."""
#     global rabbit_connection, rabbit_channel

#     try:
#         # If connection exists and is open, reuse it
#         if rabbit_connection and rabbit_connection.is_open:
#             if rabbit_channel and rabbit_channel.is_open:
#                 return rabbit_channel

#         # Otherwise create new connection
#         rabbit_connection = pika.BlockingConnection(
#             pika.ConnectionParameters(host="localhost", heartbeat=600)
#         )
#         rabbit_channel = rabbit_connection.channel()
#         # rabbit_channel.queue_declare(queue="vms_logs")

#         return rabbit_channel

#     except Exception as e:
#         print("RabbitMQ connection failed:", e)
#         rabbit_connection = None
#         rabbit_channel = None
#         return None


# def send_log_to_rabbitmq(log_message):
#     """Send log message using persistent channel."""
#     try:
#         channel = get_rabbitmq_channel()
#         channel.queue_declare(queue="vms_logs")
#         if not channel:
#             print("Cannot obtain RabbitMQ channel. Log not sent.")
#             return

#         channel.basic_publish(
#             exchange="",
#             routing_key="vms_logs",
#             body=pickle.dumps(log_message)
#         )

#     except Exception as e:
#         print(f"Failed to send log to RabbitMQ: {e}")
#         # Reset connection so next call will reconnect
#         global rabbit_connection, rabbit_channel
#         rabbit_connection = None
#         rabbit_channel = None



# def log_info(message):
#     """Log an INFO event."""
#     current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#     data = {
#         "log_level": "INFO",
#         "Event_Type": "Push RTSPULR into Queue by API",
#         "Message": message,
#         "datetime": current_time,
#     }
#     logging.info(message)
#     send_log_to_rabbitmq(data)


# def log_exception(message):
#     """Log an EXCEPTION event."""
#     current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#     data = {
#         "log_level": "EXCEPTION",
#         "Event_Type": "Push RTSPULR into Queue by API",
#         "Message": message,
#         "datetime": current_time,
#     }
#     logging.error(message)
#     send_log_to_rabbitmq(data)

# # ---------------------------------------------------------
# # Camera API
# # ---------------------------------------------------------
# @app.route('/EventCameraDetails', methods=['POST'])
# def update_camera_details():
#     """API endpoint to update camera configuration."""
#     data = request.get_json()
#     print("Incoming Data:", data)

#     cameras = data.get("cameras", [])
#     if not cameras:
#         log_exception("No cameras provided in the request.")
#         return jsonify({"error": "No cameras provided!"}), 400

#     for camera in cameras:
#         required = ["camera_id", "url"]
#         missing = [f for f in required if f not in camera]

#         if missing:
#             log_exception(
#                 f"Missing required fields: {missing} for camera {camera.get('camera_id', 'Unknown')}"
#             )
#             return (
#                 jsonify(
#                     {
#                         "error": f"Missing required fields for camera {camera.get('camera_id')}!"
#                     }
#                 ),
#                 400,
#             )

#         camera_id = camera["camera_id"]
#         camera_url = camera["url"]
#         running = camera.get("running", False)
#         #user_id = camera["user_id"]
#         event_dic = camera.get("event_dic", {})

#         print("Event Dic:", event_dic, type(event_dic))
#         # get Rabbitmq channel
#         sent_channel = get_rabbitmq_channel()
#         sent_channel.exchange_declare(exchange="rtspurl_for_framer", exchange_type="fanout", durable=True)
       
#         frame_data = {
#             "CameraId": camera_id,
#             "CameraUrl": camera_url,
#             "Running": running,
#             "EventDic": event_dic,
#         }

#         print("Frame Data:", frame_data)

#         try:
#             sent_channel.basic_publish(
#                 exchange="rtspurl_for_framer",
#                 routing_key="",
#                 body=pickle.dumps(frame_data),
#             )
#             log_info(f"Published camera {camera_id} details to RabbitMQ.")
#         except Exception as e:
#             log_exception(f"Failed to publish message for camera {camera_id}: {e}")

#     log_info("All cameras added/updated successfully.")
#     return jsonify({"message": "Cameras added/updated successfully!"}), 201

# # ---------------------------------------------------------
# # File Serving Endpoint
# # ---------------------------------------------------------
# @app.route('/app/<folder>/<camera_id>/<filename>')
# def get_image(folder, camera_id, filename):
#     """Serve images from a specific folder."""
#     camera_folder = os.path.join(os.getcwd(), folder, camera_id)
#     print("Serving image from:", camera_folder)
#     return send_from_directory(camera_folder, filename)

# # ---------------------------------------------------------
# # Main Entry
# # ---------------------------------------------------------
# if __name__ == '__main__':
#     app.run(host='0.0.0.0', port=6566, debug=True)




from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import pickle
import pika
import logging
import datetime
import os
import time

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------
# RabbitMQ Lazy Persistent Connection
# ---------------------------------------------------------
rabbit_connection = None
rabbit_channel = None

def get_rabbitmq_channel():
    """Create and reuse a persistent RabbitMQ channel."""
    global rabbit_connection, rabbit_channel

    try:
        if rabbit_connection and rabbit_connection.is_open:
            if rabbit_channel and rabbit_channel.is_open:
                return rabbit_channel

        rabbit_connection = pika.BlockingConnection(
            pika.ConnectionParameters(host="localhost", heartbeat=600)
        )
        rabbit_channel = rabbit_connection.channel()
        return rabbit_channel

    except Exception as e:
        print("RabbitMQ connection failed:", e)
        rabbit_connection = None
        rabbit_channel = None
        return None


# ---------------------------------------------------------
# Logging Helpers
# ---------------------------------------------------------
def send_log_to_rabbitmq(log_message):
    try:
        channel = get_rabbitmq_channel()
        if not channel:
            print("Log send failed: No channel")
            return

        channel.queue_declare(queue="vms_logs")

        channel.basic_publish(
            exchange="",
            routing_key="vms_logs",
            body=pickle.dumps(log_message)
        )

    except Exception as e:
        print(f"Failed to send log to RabbitMQ: {e}")
        global rabbit_connection, rabbit_channel
        rabbit_connection = None
        rabbit_channel = None


def log_info(message):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data = {
        "log_level": "INFO",
        "Event_Type": "Push RTSPULR into Queue by API",
        "Message": message,
        "datetime": now,
    }
    logging.info(message)
    send_log_to_rabbitmq(data)


def log_exception(message):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data = {
        "log_level": "EXCEPTION",
        "Event_Type": "Push RTSPULR into Queue by API",
        "Message": message,
        "datetime": now,
    }
    logging.error(message)
    send_log_to_rabbitmq(data)


# ---------------------------------------------------------
# API Endpoint — Updated for New Payload
# ---------------------------------------------------------
@app.route('/EventCameraDetails', methods=['POST'])
def update_camera_details():

    data = request.get_json()
    print("Incoming Payload:", data)

    cameras = data.get("cameras", [])
    if not cameras:
        log_exception("No cameras provided in request")
        return jsonify({"error": "No cameras provided!"}), 400

    channel = get_rabbitmq_channel()
    if not channel:
        return jsonify({"error": "RabbitMQ unavailable"}), 500

    channel.exchange_declare(
        exchange="rtspurl_for_framer",
        exchange_type="fanout",
        durable=True
    )

    # -------------------------------------------------
    # Process Each Camera Block
    # -------------------------------------------------
    for cam in cameras:

        # ---------------------------------------------
        # REQUIRED FIELDS VALIDATION
        # ---------------------------------------------
        required_fields = ["camera_id", "url", "events", "event_rules", "running", "user_id"]

        missing = [f for f in required_fields if f not in cam]

        if missing:
            log_exception(f"Missing fields: {missing} in camera block")
            return jsonify({"error": f"Missing required fields: {missing}"}), 400

        # ---------------------------------------------
        # Extract validated fields
        # ---------------------------------------------
        camera_ids = cam["camera_id"]
        urls = cam["url"]
        events = cam["events"]
        event_rules = cam["event_rules"]
        running = cam["running"]
        user_id = cam["user_id"]

        # Validate types for camera_id and url

        if not isinstance(camera_ids, list) or not isinstance(urls, list):
            return jsonify({"error": "camera_id and url must be lists"}), 400

        # ---------------------------------------------
        # Pair each camera_id with each url
        # Example:
        # camera_id: [10,20]
        # url: ["u1","u2"]
        # -> produces 4 messages
        framers_data = {
            "CameraIds": camera_ids,
            "CameraUrls": urls,
            "Running": running,
            "UserId": user_id,
            "Events": events,
            "EventRules": event_rules
                    }
        print("Sending:", framers_data)

        try:
            channel.basic_publish(
                exchange="rtspurl_for_framer",
                routing_key="",
                body=pickle.dumps(framers_data)
            )
            log_info(f"Published camera {camera_ids} URL {urls} to RabbitMQ.")
        except Exception as e:
            log_exception(f"Failed to publish message for camera {camera_ids}: {e}")
        # ---------------------------------------------
        # for cid in camera_ids:
        #     for curl in urls:

        #         frame_data = {
        #             "CameraId": cid,
        #             "CameraUrl": curl,
        #             "Running": running,
        #             "UserId": user_id,
        #             "Events": events,
        #             "CustomEvents": custom_events
        #         }

        #         print("Sending:", frame_data)

        #         try:
        #             channel.basic_publish(
        #                 exchange="rtspurl_for_framer",
        #                 routing_key="",
        #                 body=pickle.dumps(frame_data)
        #             )
        #             log_info(f"Published camera {cid} URL {curl} to RabbitMQ.")
        #         except Exception as e:
        #             log_exception(f"Failed to publish message for camera {cid}: {e}")

    log_info("All camera data processed successfully.")
    return jsonify({"message": "Cameras added/updated successfully!"}), 201


# ---------------------------------------------------------
# File Serving Endpoint
# ---------------------------------------------------------
@app.route('/app/<folder>/<camera_id>/<filename>')
def get_image(folder, camera_id, filename):
    folder_path = os.path.join(os.getcwd(), folder, camera_id)
    return send_from_directory(folder_path, filename)


# ---------------------------------------------------------
# Main Entry
# ---------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
