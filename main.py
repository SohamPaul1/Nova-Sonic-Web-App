import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

import asyncio
import base64
import json
import uuid
import warnings
import pytz
import random
import hashlib
import datetime
import time
import inspect
import logging

# Set up comprehensive logger
logger = logging.getLogger("nova_sonic")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler("Agent.log")
formatter = logging.Formatter('%(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

def get_current_time_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from starlette.websockets import WebSocketState

from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient, InvokeModelWithBidirectionalStreamOperationInput
from aws_sdk_bedrock_runtime.models import InvokeModelWithBidirectionalStreamInputChunk, BidirectionalInputPayloadPart
from aws_sdk_bedrock_runtime.config import Config
from smithy_aws_core.identity.environment import EnvironmentCredentialsResolver

# Suppress warnings
warnings.filterwarnings("ignore")

# Audio configuration (Bedrock protocol)
INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000

# Debug mode flag
DEBUG = False

def debug_print(message):
    """Print only if debug mode is enabled"""
    if DEBUG:
        functionName = inspect.stack()[1].function
        if  functionName == 'time_it' or functionName == 'time_it_async':
            functionName = inspect.stack()[2].function
        print('{:%Y-%m-%d %H:%M:%S.%f}'.format(datetime.datetime.now())[:-3] + ' ' + functionName + ' ' + message)

def time_it(label, methodToRun):
    start_time = time.perf_counter()
    result = methodToRun()
    end_time = time.perf_counter()
    debug_print(f"Execution time for {label}: {end_time - start_time:.4f} seconds")
    return result

async def time_it_async(label, methodToRun):
    start_time = time.perf_counter()
    result = await methodToRun()
    end_time = time.perf_counter()
    debug_print(f"Execution time for {label}: {end_time - start_time:.4f} seconds")
    return result

class ToolProcessor:
    def __init__(self):
        # ThreadPoolExecutor could be used for complex implementations
        self.tasks = {}
    
    async def process_tool_async(self, tool_name, tool_content):
        """Process a tool call asynchronously and return the result"""
        # Create a unique task ID
        task_id = str(uuid.uuid4())
        
        # Create and store the task
        task = asyncio.create_task(self._run_tool(tool_name, tool_content))
        self.tasks[task_id] = task
        
        try:
            # Wait for the task to complete
            result = await task
            return result
        finally:
            # Clean up the task reference
            if task_id in self.tasks:
                del self.tasks[task_id]
    
    async def _run_tool(self, tool_name, tool_content):
        """Internal method to execute the tool logic"""
        debug_print(f"Processing tool: {tool_name}")
        tool = tool_name.lower()
        
        if tool == "getdateandtimetool":
            # Get current date in PST timezone
            pst_timezone = pytz.timezone("America/Los_Angeles")
            pst_date = datetime.datetime.now(pst_timezone)
            
            return {
                "formattedTime": pst_date.strftime("%I:%M %p"),
                "date": pst_date.strftime("%Y-%m-%d"),
                "year": pst_date.year,
                "month": pst_date.month,
                "day": pst_date.day,
                "dayOfWeek": pst_date.strftime("%A").upper(),
                "timezone": "PST"
            }
        
        elif tool == "trackordertool":
            # Simulate a long-running operation
            debug_print(f"TrackOrderTool starting operation that will take time...")
            await asyncio.sleep(10)  # Non-blocking sleep to simulate processing time
            
            # Extract order ID from toolUseContent
            content = tool_content.get("content", {})
            content_data = json.loads(content)
            order_id = content_data.get("orderId", "")
            request_notifications = content_data.get("requestNotifications", False)
            
            # Convert order_id to string if it's an integer
            if isinstance(order_id, int):
                order_id = str(order_id)
            # Validate order ID format
            if not order_id or not isinstance(order_id, str):
                return {
                    "error": "Invalid order ID format",
                    "orderStatus": "",
                    "estimatedDelivery": "",
                    "lastUpdate": ""
                }
            
            # Create deterministic randomness based on order ID
            # This ensures the same order ID always returns the same status
            seed = int(hashlib.md5(order_id.encode(), usedforsecurity=False).hexdigest(), 16) % 10000
            random.seed(seed)
            
            # Rest of the order tracking logic
            statuses = [
                "Order received", 
                "Processing", 
                "Preparing for shipment",
                "Shipped",
                "In transit", 
                "Out for delivery",
                "Delivered",
                "Delayed"
            ]
            
            weights = [10, 15, 15, 20, 20, 10, 5, 3]
            status = random.choices(statuses, weights=weights, k=1)[0]
            
            # Generate delivery date logic
            today = datetime.datetime.now()
            if status == "Delivered":
                delivery_days = -random.randint(0, 3)
                estimated_delivery = (today + datetime.timedelta(days=delivery_days)).strftime("%Y-%m-%d")
            elif status == "Out for delivery":
                estimated_delivery = today.strftime("%Y-%m-%d")
            else:
                delivery_days = random.randint(1, 10)
                estimated_delivery = (today + datetime.timedelta(days=delivery_days)).strftime("%Y-%m-%d")

            # Handle notification request
            notification_message = ""
            if request_notifications and status != "Delivered":
                notification_message = f"You will receive notifications for order {order_id}"

            # Return tracking information
            tracking_info = {
                "orderStatus": status,
                "orderNumber": order_id,
                "notificationStatus": notification_message
            }

            # Add appropriate fields based on status
            if status == "Delivered":
                tracking_info["deliveredOn"] = estimated_delivery
            elif status == "Out for delivery":
                tracking_info["expectedDelivery"] = "Today"
            else:
                tracking_info["estimatedDelivery"] = estimated_delivery

            # Add location information based on status
            if status == "In transit":
                tracking_info["currentLocation"] = "Distribution Center"
            elif status == "Delivered":
                tracking_info["deliveryLocation"] = "Front Door"
                
            # Add additional info for delayed status
            if status == "Delayed":
                tracking_info["additionalInfo"] = "Weather delays possible"
                
            debug_print(f"TrackOrderTool completed successfully")
            return tracking_info
        else:
            return {
                "error": f"Unsupported tool: {tool_name}"
            }

class BedrockStreamManager:
    """Manages bidirectional streaming with AWS Bedrock using asyncio"""
    
    # Event templates
    START_SESSION_EVENT = '''{
        "event": {
            "sessionStart": {
            "inferenceConfiguration": {
                "maxTokens": 1024,
                "topP": 0.9,
                "temperature": 0.7
                }
            }
        }
    }'''

    CONTENT_START_EVENT = '''{
        "event": {
            "contentStart": {
            "promptName": "%s",
            "contentName": "%s",
            "type": "AUDIO",
            "interactive": true,
            "role": "USER",
            "audioInputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": 16000,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "audioType": "SPEECH",
                "encoding": "base64"
                }
            }
        }
    }'''

    AUDIO_EVENT_TEMPLATE = '''{
        "event": {
            "audioInput": {
            "promptName": "%s",
            "contentName": "%s",
            "content": "%s"
            }
        }
    }'''

    TEXT_CONTENT_START_EVENT = '''{
        "event": {
            "contentStart": {
            "promptName": "%s",
            "contentName": "%s",
            "type": "TEXT",
            "role": "%s",
            "interactive": false,
                "textInputConfiguration": {
                    "mediaType": "text/plain"
                }
            }
        }
    }'''

    TEXT_INPUT_EVENT = '''{
        "event": {
            "textInput": {
            "promptName": "%s",
            "contentName": "%s",
            "content": "%s"
            }
        }
    }'''
    
    USER_TEXT_CONTENT_START_EVENT = '''{
        "event": {
            "contentStart": {
            "promptName": "%s",
            "contentName": "%s",
            "type": "TEXT",
            "role": "USER",
            "interactive": true,
                "textInputConfiguration": {
                    "mediaType": "text/plain"
                }
            }
        }
    }'''

    TOOL_CONTENT_START_EVENT = '''{
        "event": {
            "contentStart": {
                "promptName": "%s",
                "contentName": "%s",
                "interactive": false,
                "type": "TOOL",
                "role": "TOOL",
                "toolResultInputConfiguration": {
                    "toolUseId": "%s",
                    "type": "TEXT",
                    "textInputConfiguration": {
                        "mediaType": "text/plain"
                    }
                }
            }
        }
    }'''

    CONTENT_END_EVENT = '''{
        "event": {
            "contentEnd": {
            "promptName": "%s",
            "contentName": "%s"
            }
        }
    }'''

    PROMPT_END_EVENT = '''{
        "event": {
            "promptEnd": {
            "promptName": "%s"
            }
        }
    }'''

    SESSION_END_EVENT = '''{
        "event": {
            "sessionEnd": {}
        }
    }'''
    
    def start_prompt(self):
        """Create a promptStart event"""
        get_default_tool_schema = json.dumps({
            "type": "object",
            "properties": {},
            "required": []
        })

        get_order_tracking_schema = json.dumps({
            "type": "object",
            "properties": {
                "orderId": {
                    "type": "string",
                    "description": "The order number or ID to track"
                },
                "requestNotifications": {
                    "type": "boolean",
                    "description": "Whether to set up notifications for this order",
                    "default": False
                }
            },
            "required": ["orderId"]
        })

        
        prompt_start_event = {
            "event": {
                "promptStart": {
                    "promptName": self.prompt_name,
                    "textOutputConfiguration": {
                        "mediaType": "text/plain"
                    },
                    "audioOutputConfiguration": {
                        "mediaType": "audio/lpcm",
                        "sampleRateHertz": 24000,
                        "sampleSizeBits": 16,
                        "channelCount": 1,
                        "voiceId": "matthew",
                        "encoding": "base64",
                        "audioType": "SPEECH"
                    },
                    "toolUseOutputConfiguration": {
                        "mediaType": "application/json"
                    },
                    "toolConfiguration": {
                        "tools": [
                            {
                                "toolSpec": {
                                    "name": "getDateAndTimeTool",
                                    "description": "get information about the current date and time",
                                    "inputSchema": {
                                        "json": get_default_tool_schema
                                    }
                                }
                            },
                            {
                                "toolSpec": {
                                    "name": "trackOrderTool",
                                    "description": "Retrieves real-time order tracking information and detailed status updates for customer orders by order ID. Provides estimated delivery dates. Use this tool when customers ask about their order status or delivery timeline.",
                                    "inputSchema": {
                                    "json": get_order_tracking_schema
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        }
        
        return json.dumps(prompt_start_event)
    
    def tool_result_event(self, content_name, content, role):
        """Create a tool result event"""

        if isinstance(content, dict):
            content_json_string = json.dumps(content)
        else:
            content_json_string = content
            
        tool_result_event = {
            "event": {
                "toolResult": {
                    "promptName": self.prompt_name,
                    "contentName": content_name,
                    "content": content_json_string
                }
            }
        }
        return json.dumps(tool_result_event)
   
    def __init__(self, model_id='amazon.nova-sonic-v1:0', region='us-east-1'):
        """Initialize the stream manager."""
        self.model_id = model_id
        self.region = region
        
        # Asyncio queues for audio I/O
        self.audio_input_queue = asyncio.Queue()
        self.client_queue = asyncio.Queue()  # Messages bound for the WebSocket client
        self.output_queue = asyncio.Queue()
        
        self.response_task = None
        self.stream_response = None
        self.is_active = False
        self.barge_in = False
        self.bedrock_client = None
        
        # Text response components
        self.display_assistant_text = False
        self.role = None

        # Session information
        self.prompt_name = str(uuid.uuid4())
        self.content_name = str(uuid.uuid4())
        self.audio_content_name = str(uuid.uuid4())
        self.toolUseContent = ""
        self.toolUseId = ""
        self.toolName = ""

        # Add a tool processor
        self.tool_processor = ToolProcessor()
        
        # Add tracking for in-progress tool calls
        self.pending_tool_tasks = {}

    def _initialize_client(self):
        """Initialize the Bedrock client."""
        config = Config(
            endpoint_uri=f"https://bedrock-runtime.{self.region}.amazonaws.com",
            region=self.region,
            aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
        )
        self.bedrock_client = BedrockRuntimeClient(config=config)
    
    async def initialize_stream(self):
        """Initialize the bidirectional stream with Bedrock."""
        if not self.bedrock_client:
            self._initialize_client()
        
        try:
            self.stream_response = await time_it_async("invoke_model_with_bidirectional_stream", lambda : self.bedrock_client.invoke_model_with_bidirectional_stream( InvokeModelWithBidirectionalStreamOperationInput(model_id=self.model_id)))
            self.is_active = True

            # Read system prompt from prompt.txt
            prompt_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt.txt")
            try:
                with open(prompt_file, "r") as f:
                    default_system_prompt = f.read().strip()
                debug_print(f"Loaded system prompt from {prompt_file}")
            except FileNotFoundError:
                default_system_prompt = "You are a friend. The user and you will engage in a spoken dialog exchanging the transcripts of a natural real-time conversation."
                debug_print("prompt.txt not found, using default system prompt")
            
            # Send initialization events
            prompt_event = self.start_prompt()
            text_content_start = self.TEXT_CONTENT_START_EVENT % (self.prompt_name, self.content_name, "SYSTEM")
            text_content = self.TEXT_INPUT_EVENT % (self.prompt_name, self.content_name, default_system_prompt)
            text_content_end = self.CONTENT_END_EVENT % (self.prompt_name, self.content_name)
            
            init_events = [self.START_SESSION_EVENT, prompt_event, text_content_start, text_content, text_content_end]
            
            for event in init_events:
                await self.send_raw_event(event)
                # Small delay between init events
                await asyncio.sleep(0.1)
            
            # Start listening for responses
            self.response_task = asyncio.create_task(self._process_responses())
            
            # Start processing audio input
            asyncio.create_task(self._process_audio_input())
            
            # Wait a bit to ensure everything is set up
            await asyncio.sleep(0.1)
            
            debug_print("Stream initialized successfully")
            return self
        except Exception as e:
            self.is_active = False
            print(f"Failed to initialize stream: {str(e)}")
            raise
    
    async def send_raw_event(self, event_json):
        """Send a raw event JSON to the Bedrock stream."""
        if not self.stream_response or not self.is_active:
            debug_print("Stream not initialized or closed")
            return
       
        event = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=event_json.encode('utf-8'))
        )
        
        try:
            await self.stream_response.input_stream.send(event)
            # For debugging large events, you might want to log just the type
            if DEBUG:
                if len(event_json) > 200:
                    event_type = json.loads(event_json).get("event", {}).keys()
                    debug_print(f"Sent event type: {list(event_type)}")
                else:
                    debug_print(f"Sent event: {event_json}")
        except Exception as e:
            debug_print(f"Error sending event: {str(e)}")
            if DEBUG:
                import traceback
                traceback.print_exc()
    
    async def send_audio_content_start_event(self):
        """Send a content start event to the Bedrock stream."""
        content_start_event = self.CONTENT_START_EVENT % (self.prompt_name, self.audio_content_name)
        await self.send_raw_event(content_start_event)
    
    async def _process_audio_input(self):
        """Process audio input from the queue and send to Bedrock."""
        while self.is_active:
            try:
                # Get audio data from the queue
                data = await self.audio_input_queue.get()
                
                audio_bytes = data.get('audio_bytes')
                if not audio_bytes:
                    debug_print("No audio bytes received")
                    continue
                
                # Base64 encode the audio data
                blob = base64.b64encode(audio_bytes)
                audio_event = self.AUDIO_EVENT_TEMPLATE % (
                    self.prompt_name, 
                    self.audio_content_name, 
                    blob.decode('utf-8')
                )
                
                # Send the event
                await self.send_raw_event(audio_event)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                debug_print(f"Error processing audio: {e}")
                if DEBUG:
                    import traceback
                    traceback.print_exc()
    
    def add_audio_chunk(self, audio_bytes):
        """Add an audio chunk to the queue."""
        self.audio_input_queue.put_nowait({
            'audio_bytes': audio_bytes,
            'prompt_name': self.prompt_name,
            'content_name': self.audio_content_name
        })
    
    async def send_audio_content_end_event(self):
        """Send a content end event to the Bedrock stream."""
        if not self.is_active:
            debug_print("Stream is not active")
            return
        
        content_end_event = self.CONTENT_END_EVENT % (self.prompt_name, self.audio_content_name)
        await self.send_raw_event(content_end_event)
        debug_print("Audio ended")
    
    async def send_tool_start_event(self, content_name, tool_use_id):
        """Send a tool content start event to the Bedrock stream."""
        content_start_event = self.TOOL_CONTENT_START_EVENT % (self.prompt_name, content_name, tool_use_id)
        debug_print(f"Sending tool start event: {content_start_event}")  
        await self.send_raw_event(content_start_event)

    async def send_tool_result_event(self, content_name, tool_result):
        """Send a tool content event to the Bedrock stream."""
        # Use the actual tool result from processToolUse
        tool_result_event = self.tool_result_event(content_name=content_name, content=tool_result, role="TOOL")
        debug_print(f"Sending tool result event: {tool_result_event}")
        await self.send_raw_event(tool_result_event)
    
    async def send_tool_content_end_event(self, content_name):
        """Send a tool content end event to the Bedrock stream."""
        tool_content_end_event = self.CONTENT_END_EVENT % (self.prompt_name, content_name)
        debug_print(f"Sending tool content event: {tool_content_end_event}")
        await self.send_raw_event(tool_content_end_event)
    
    async def send_prompt_end_event(self):
        """Close the stream and clean up resources."""
        if not self.is_active:
            debug_print("Stream is not active")
            return
        
        prompt_end_event = self.PROMPT_END_EVENT % (self.prompt_name)
        await self.send_raw_event(prompt_end_event)
        debug_print("Prompt ended")
        
    async def send_session_end_event(self):
        """Send a session end event to the Bedrock stream."""
        if not self.is_active:
            debug_print("Stream is not active")
            return

        await self.send_raw_event(self.SESSION_END_EVENT)
        self.is_active = False
        debug_print("Session ended")
        
    async def send_user_text(self, text):
        """Send a user text message to the model in the middle of a session."""
        if not self.is_active:
            debug_print("Stream is not active, cannot send text")
            return
            
        debug_print(f"Sending user text: {text}")
        
        # 1. End current audio block
        await self.send_audio_content_end_event()
        
        # 2. Start text block
        text_content_name = str(uuid.uuid4())
        text_content_start = self.USER_TEXT_CONTENT_START_EVENT % (self.prompt_name, text_content_name)
        await self.send_raw_event(text_content_start)
        
        # 3. Send text payload
        text_content = self.TEXT_INPUT_EVENT % (self.prompt_name, text_content_name, text)
        await self.send_raw_event(text_content)
        
        # 4. End text block
        text_content_end = self.CONTENT_END_EVENT % (self.prompt_name, text_content_name)
        await self.send_raw_event(text_content_end)
        
        # 5. Start new audio block (update audio_content_name so subsequent audio goes here)
        self.audio_content_name = str(uuid.uuid4())
        await self.send_audio_content_start_event()
    
    async def _process_responses(self):
        """Process incoming responses from Bedrock and forward to the client queue."""
        try:            
            while self.is_active:
                try:
                    output = await self.stream_response.await_output()
                    result = await output[1].receive()
                    if result.value and result.value.bytes_:
                        try:
                            response_data = result.value.bytes_.decode('utf-8')
                            json_data = json.loads(response_data)
                            
                            # Handle different response types
                            if 'event' in json_data:
                                if 'completionStart' in json_data['event']:
                                    debug_print(f"completionStart: {json_data['event']}")
                                elif 'contentStart' in json_data['event']:
                                    debug_print("Content start detected")
                                    content_start = json_data['event']['contentStart']
                                    # set role
                                    self.role = content_start['role']
                                    
                                    if self.role == "USER":
                                        logger.info(f"🗣️ [TIMING] User started speaking at: {get_current_time_str()}")
                                    elif self.role == "ASSISTANT":
                                        logger.info(f"🤖 [TIMING] AI Agent started speaking at: {get_current_time_str()}")

                                    # Check for speculative content
                                    if 'additionalModelFields' in content_start:
                                        try:
                                            additional_fields = json.loads(content_start['additionalModelFields'])
                                            if additional_fields.get('generationStage') == 'SPECULATIVE':
                                                debug_print("Speculative content detected")
                                                self.display_assistant_text = True
                                            else:
                                                self.display_assistant_text = False
                                        except json.JSONDecodeError:
                                            debug_print("Error parsing additionalModelFields")
                                elif 'textOutput' in json_data['event']:
                                    text_content = json_data['event']['textOutput']['content']
                                    role = json_data['event']['textOutput']['role']
                                    # Check if there is a barge-in
                                    if '{ "interrupted" : true }' in text_content:
                                        debug_print("Barge-in detected. Stopping audio output.")
                                        self.barge_in = True
                                        current_time = get_current_time_str()
                                        logger.info(f"🚨 [BARGE-IN] User interrupted AI at: {current_time}")
                                        logger.info(f"🤖 [TIMING] AI Agent was interrupted at: {current_time}")
                                        await self.client_queue.put({"type": "barge_in"})

                                    if (self.role == "ASSISTANT" and self.display_assistant_text):
                                        await self.client_queue.put({"type": "assistant_text", "text": text_content})
                                    elif (self.role == "USER"):
                                        await self.client_queue.put({"type": "user_text", "text": text_content})
                                elif 'audioOutput' in json_data['event']:
                                    audio_content = json_data['event']['audioOutput']['content']
                                    # Forward base64-encoded audio directly to the client
                                    await self.client_queue.put({"type": "audio", "data": audio_content})
                                elif 'toolUse' in json_data['event']:
                                    self.toolUseContent = json_data['event']['toolUse']
                                    self.toolName = json_data['event']['toolUse']['toolName']
                                    self.toolUseId = json_data['event']['toolUse']['toolUseId']
                                    input_args = self.toolUseContent.get('input', {})
                                    logger.info(f"🔧 [TOOL CALL] {self.toolName} — args: {json.dumps(input_args)}")
                                    debug_print(f"Tool use detected: {self.toolName}, ID: {self.toolUseId}")
                                elif 'contentEnd' in json_data['event'] and json_data['event'].get('contentEnd', {}).get('type') == 'TOOL':
                                    debug_print("Processing tool use and sending result")
                                     # Start asynchronous tool processing - non-blocking
                                    self.handle_tool_request(self.toolName, self.toolUseContent, self.toolUseId)
                                    debug_print("Processing tool use asynchronously")
                                elif 'contentEnd' in json_data['event']:
                                    debug_print("Content end")
                                    if self.role == "USER":
                                        logger.info(f"🗣️ [TIMING] User finished speaking at: {get_current_time_str()}")
                                    elif self.role == "ASSISTANT":
                                        if not self.barge_in:
                                            logger.info(f"🤖 [TIMING] AI Agent finished speaking at: {get_current_time_str()}")
                                        self.barge_in = False
                                elif 'completionEnd' in json_data['event']:
                                    # Handle end of conversation, no more response will be generated
                                    debug_print("End of response sequence")
                                elif 'usageEvent' in json_data['event']:
                                    debug_print(f"UsageEvent: {json_data['event']}")
                            # Put the response in the output queue for other components
                            await self.output_queue.put(json_data)
                        except json.JSONDecodeError:
                            await self.output_queue.put({"raw_data": response_data})
                except StopAsyncIteration:
                    # Stream has ended
                    break
                except Exception as e:
                   # Handle ValidationException properly
                    if "ValidationException" in str(e):
                        error_message = str(e)
                        print(f"Validation error: {error_message}")
                    else:
                        print(f"Error receiving response: {e}")
                    break
                    
        except Exception as e:
            print(f"Response processing error: {e}")
        finally:
            self.is_active = False
            try:
                await self.client_queue.put({"type": "status", "message": "session_ended"})
            except Exception:
                pass

    def handle_tool_request(self, tool_name, tool_content, tool_use_id):
        """Handle a tool request asynchronously"""
        # Create a unique content name for this tool response
        tool_content_name = str(uuid.uuid4())
        
        # Create an asynchronous task for the tool execution
        task = asyncio.create_task(self._execute_tool_and_send_result(
            tool_name, tool_content, tool_use_id, tool_content_name))
        
        # Store the task
        self.pending_tool_tasks[tool_content_name] = task
        
        # Add error handling
        task.add_done_callback(
            lambda t: self._handle_tool_task_completion(t, tool_content_name))
    
    def _handle_tool_task_completion(self, task, content_name):
        """Handle the completion of a tool task"""
        # Remove task from pending tasks
        if content_name in self.pending_tool_tasks:
            del self.pending_tool_tasks[content_name]
        
        # Handle any exceptions
        if task.done() and not task.cancelled():
            exception = task.exception()
            if exception:
                debug_print(f"Tool task failed: {str(exception)}")
    
    async def _execute_tool_and_send_result(self, tool_name, tool_content, tool_use_id, content_name):
        """Execute a tool and send the result"""
        try:
            debug_print(f"Starting tool execution: {tool_name}")
            
            # Process the tool - this doesn't block the event loop
            start_time = time.perf_counter()
            tool_result = await self.tool_processor.process_tool_async(tool_name, tool_content)
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            
            logger.info(f"🔧 [TOOL RESULT READY] {tool_name} — {duration_ms}ms — result: {json.dumps(tool_result)}")
            
            # Send the result sequence
            await self.send_tool_start_event(content_name, tool_use_id)
            await self.send_tool_result_event(content_name, tool_result)
            await self.send_tool_content_end_event(content_name)
            
            debug_print(f"Tool execution complete: {tool_name}")
        except Exception as e:
            debug_print(f"Error executing tool {tool_name}: {str(e)}")
            # Try to send an error response if possible
            try:
                error_result = {"error": f"Tool execution failed: {str(e)}"}
                
                await self.send_tool_start_event(content_name, tool_use_id)
                await self.send_tool_result_event(content_name, error_result)
                await self.send_tool_content_end_event(content_name)
            except Exception as send_error:
                debug_print(f"Failed to send error response: {str(send_error)}")
    
    async def close(self):
        """Close the stream properly."""
        if not self.is_active:
            return
            
        self.is_active = False
        
        # Cancel any pending tool tasks
        for task in self.pending_tool_tasks.values():
            task.cancel()

        # Send closing sequence gracefully
        try:
            await self.send_audio_content_end_event()
            await self.send_prompt_end_event()
            await self.send_session_end_event()
            
            # Give the server a moment to send the final ACK and close the output stream gracefully
            if self.response_task and not self.response_task.done():
                try:
                    await asyncio.wait_for(self.response_task, timeout=1.0)
                except asyncio.TimeoutError:
                    debug_print("Response task didn't close in time, cancelling...")
                    self.response_task.cancel()
        except Exception as e:
            debug_print(f"Error during graceful shutdown: {e}")

        if self.stream_response:
            try:
                await self.stream_response.input_stream.close()
            except Exception:
                pass


# ==================== FastAPI Application ====================

app = FastAPI(title="Nova Sonic Web App")


@app.get("/")
async def get_index():
    """Serve the main web interface."""
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
    with open(html_path, "r") as f:
        return HTMLResponse(content=f.read())


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle WebSocket connections for real-time audio streaming."""
    await websocket.accept()
    
    region = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
    model_id = os.environ.get('MODEL_ID', 'amazon.nova-sonic-v1:0')
    stream_manager = BedrockStreamManager(model_id=model_id, region=region)
    
    try:
        # Initialize the Bedrock bidirectional stream
        await stream_manager.initialize_stream()
        
        # Start the audio content block (one per session)
        await stream_manager.send_audio_content_start_event()
        
        # Notify the client that the stream is ready
        await websocket.send_json({"type": "status", "message": "connected"})
        debug_print("WebSocket client connected and Bedrock stream initialized")
        
        async def forward_to_client():
            """Forward messages from Bedrock (via client_queue) to the WebSocket client."""
            try:
                while stream_manager.is_active:
                    try:
                        msg = await asyncio.wait_for(
                            stream_manager.client_queue.get(),
                            timeout=0.5
                        )
                        if websocket.client_state == WebSocketState.CONNECTED:
                            await websocket.send_json(msg)
                    except asyncio.TimeoutError:
                        continue
            except Exception as e:
                debug_print(f"Forward to client error: {e}")
        
        async def receive_from_client():
            """Receive audio data from the WebSocket client and forward to Bedrock."""
            try:
                while stream_manager.is_active:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        break
                    if "bytes" in message:
                        # Binary audio data from the browser microphone (Int16 PCM @ 16kHz)
                        stream_manager.add_audio_chunk(message["bytes"])
                    elif "text" in message:
                        data = json.loads(message["text"])
                        if data.get("type") == "stop":
                            debug_print("Client requested stop")
                            break
                        elif data.get("type") == "user_text_input":
                            text = data.get("text", "")
                            if text:
                                await stream_manager.send_user_text(text)
            except WebSocketDisconnect:
                debug_print("WebSocket disconnected")
            except Exception as e:
                debug_print(f"Receive from client error: {e}")
        
        # Run both forwarding tasks concurrently
        forward_task = asyncio.create_task(forward_to_client())
        receive_task = asyncio.create_task(receive_from_client())
        
        # Wait for either task to complete (disconnect, stop, or error)
        done, pending = await asyncio.wait(
            [forward_task, receive_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Cancel remaining tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    
    except Exception as e:
        print(f"WebSocket error: {e}")
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json({"type": "status", "message": f"error: {str(e)}"})
        except Exception:
            pass
    finally:
        # Always clean up the Bedrock stream
        debug_print("Cleaning up Bedrock stream")
        await stream_manager.close()


# ==================== Entry Point ====================

if __name__ == "__main__":
    import uvicorn
    import argparse
    
    parser = argparse.ArgumentParser(description='Nova Sonic Web App')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    args = parser.parse_args()
    
    DEBUG = args.debug
    
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', '8009'))
    
    print(f"Starting Nova Sonic Web App on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)