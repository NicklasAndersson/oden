"""
Attachment handling for Signal messages.

Manages downloading, saving, and linking attachments from messages.
"""
import os
import json
import base64
import asyncio
import logging
import datetime
from typing import List, Dict, Any, Optional

from config import TIMEZONE
from formatting import create_message_filename

logger = logging.getLogger(__name__)


async def _get_attachment_data(attachment_id: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> Optional[str]:
    """
    Makes a JSON-RPC call to signal-cli to get attachment data by ID.
    Returns base64 encoded data if successful, otherwise None.
    """
    request_id = datetime.datetime.now().microsecond # Simple unique ID for the request
    json_request = {
        "jsonrpc": "2.0",
        "method": "getAttachment",
        "params": {
            "id": attachment_id
        },
        "id": request_id
    }
    request_str = json.dumps(json_request) + "\n"

    try:
        writer.write(request_str.encode('utf-8'))
        await writer.drain()

        # Read response line by line until our request_id is matched
        response_line = await reader.readline() # Assume response is on one line for now
        if not response_line:
            logger.error(f"No response for getAttachment request {request_id}")
            return None
        
        response = json.loads(response_line.decode('utf-8').strip())
        
        if response.get("id") == request_id and "result" in response:
            return response["result"].get("data")
        else:
            logger.error(f"Invalid or unmatched response for getAttachment: {response}")
            return None
    except Exception as e:
        logger.error(f"ERROR calling getAttachment for ID {attachment_id}: {e}")
        return None


async def save_attachments(
    attachments: List[Dict[str, Any]], 
    group_dir: str, 
    dt: datetime.datetime, 
    source_name: Optional[str], 
    source_number: Optional[str], 
    reader: asyncio.StreamReader, 
    writer: asyncio.StreamWriter
) -> List[str]:
    """Saves attachments to a subdirectory and returns a list of markdown links."""
    attachment_links = []
    if not attachments:
        return attachment_links

    # Create a unique subdirectory for attachments for this specific message entry
    attachment_subdir_name = dt.strftime("%Y%m%d%H%M%S") + "_" + create_message_filename(dt, source_name, source_number).replace(".md", "")
    attachment_dir = os.path.join(group_dir, attachment_subdir_name)
    os.makedirs(attachment_dir, exist_ok=True)

    for i, attachment in enumerate(attachments):
        data = attachment.get("data")
        filename = attachment.get("filename") or attachment.get("id")
        attachment_id = attachment.get("id")
        
        if not data and attachment_id:
            logger.info(f"Attempting to fetch attachment data for ID: {attachment_id}")
            retrieved_data = await _get_attachment_data(attachment_id, reader, writer)
            if retrieved_data:
                data = retrieved_data
                logger.info(f"Successfully fetched data for attachment ID: {attachment_id}")
            else:
                logger.warning(f"Failed to fetch data for attachment ID: {attachment_id}")

        if data and filename:
            try:
                decoded_data = base64.b64decode(data)
                safe_filename = f"{i+1}_{filename}"
                attachment_filepath = os.path.join(attachment_dir, safe_filename)
                with open(attachment_filepath, "wb") as f:
                    f.write(decoded_data)
                
                attachment_links.append(f"![[{attachment_subdir_name}/{safe_filename}]]")
                logger.info(f"Saved attachment: {attachment_filepath}")
            except Exception as e:
                logger.error(f"Could not save attachment {filename}. Error: {e}")
        else:
            missing_parts = [p for p, v in [("data", data), ("filename", filename)] if not v]
            logger.warning(f"Attachment missing {' and '.join(missing_parts)}: {attachment}")
    
    return attachment_links
