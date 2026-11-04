"""Vision management and multimodal message preparation for DeepSeek native vision API.

Provides utilities for encoding images with adaptive downscaling, building
OpenAI/DeepSeek compliant multimodal messages, and interacting directly with
DeepSeek's vision-capable chat completions endpoint without third-party proxies.
"""

import base64
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union


IMAGE_ATTACHMENT_REGEX = re.compile(
    r"\[IMAGE_ATTACHMENT(?::|\s*\]|\s+)([^\]\n\r]+)(?:\])?",
    re.IGNORECASE,
)


def extract_image_attachment_and_text(user_input: str) -> Tuple[str, Optional[str]]:
    """Extract an attached image path from user input and return the cleaned text.

    Supports formats like:
      [IMAGE_ATTACHMENT]C:/path/to/img.png
      [IMAGE_ATTACHMENT:C:/path/to/img.png]
    """
    if not user_input:
        return "", None

    match = IMAGE_ATTACHMENT_REGEX.search(user_input)
    if not match:
        return user_input, None

    image_path = match.group(1).strip()
    # Clean brackets if regex captured a trailing one
    image_path = image_path.rstrip("]").strip()
    clean_text = user_input[:match.start()] + user_input[match.end():]
    return clean_text.strip(), image_path


def image_to_data_url(
    image_path: str,
    max_dimension: int = 2048,
    quality: int = 85,
) -> str:
    """Read an image file, optionally scale it down, and return a base64 Data URL.

    Args:
        image_path: Absolute or relative path to the image file.
        max_dimension: Maximum allowed width or height in pixels.
        quality: JPEG compression quality (1-100).

    Returns:
        A Data URL string formatted as 'data:image/<format>;base64,<payload>'.
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image attachment not found at: {image_path}")

    # Determine fallback mime type from extension
    ext = os.path.splitext(image_path)[1].lower().lstrip(".")
    mime_type = "image/png" if ext == "png" else "image/jpeg"

    # Attempt high-quality downscaling and format compression via QImage if available
    try:
        from qgis.PyQt.QtCore import QBuffer, QIODevice, Qt
        from qgis.PyQt.QtGui import QImage

        image = QImage(image_path)
        if not image.isNull():
            w = image.width()
            h = image.height()
            if w > max_dimension or h > max_dimension:
                image = image.scaled(
                    max_dimension,
                    max_dimension,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )

            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            # Use JPEG for photographic / large images to conserve tokens, PNG for crisp lines
            save_format = "PNG" if ext == "png" and max(w, h) <= 1024 else "JPEG"
            image.save(buffer, save_format, quality)
            raw_bytes = bytes(buffer.data())
            buffer.close()

            mime = "image/png" if save_format == "PNG" else "image/jpeg"
            b64_str = base64.b64encode(raw_bytes).decode("utf-8")
            return f"data:{mime};base64,{b64_str}"
    except Exception:
        pass

    # Standard fallback: read bytes directly
    with open(image_path, "rb") as f:
        raw_bytes = f.read()

    b64_str = base64.b64encode(raw_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{b64_str}"


def build_multimodal_message(
    text: str,
    image_path: Optional[str] = None,
    max_dimension: int = 2048,
) -> Dict[str, Any]:
    """Construct an OpenAI/DeepSeek-compliant user message dictionary.

    If an image path is provided and exists, creates a multimodal content list
    with 'text' and 'image_url' blocks. Otherwise, returns a plain text message.
    """
    if not image_path:
        return {"role": "user", "content": text or ""}

    try:
        data_url = image_to_data_url(image_path, max_dimension=max_dimension)
        content: List[Dict[str, Any]] = []
        if text:
            content.append({"type": "text", "text": text})
        content.append({
            "type": "image_url",
            "image_url": {"url": data_url},
        })
        return {"role": "user", "content": content}
    except Exception as e:
        # Graceful degradation if image encoding fails
        fallback_text = (text or "") + f"\n\n[Warning: Attached image '{image_path}' could not be processed: {e}]"
        return {"role": "user", "content": fallback_text}


def extract_text_content(content: Union[str, List[Dict[str, Any]], Any]) -> str:
    """Extract plain text from either a string or a multimodal content block list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text_parts.append(str(block.get("text", "")))
        return "\n".join(filter(None, text_parts))
    return str(content or "")


def call_deepseek_vision(
    client: Any,
    model: str,
    prompt: str,
    image_path_or_url: str,
    system_prompt: Optional[str] = None,
    max_tokens: int = 1024,
) -> str:
    """Directly query DeepSeek's vision multimodal API.

    Args:
        client: An initialized OpenAI client pointed at DeepSeek's base URL.
        model: Model identifier (e.g. 'deepseek-chat' or vision-capable model).
        prompt: User question or instruction about the image.
        image_path_or_url: Local file path or pre-built Data URL.
        system_prompt: Optional system instruction.
        max_tokens: Max completion tokens.

    Returns:
        The text response from the model.
    """
    if not client:
        raise ValueError("DeepSeek API client is not initialized.")

    if image_path_or_url.startswith("data:image/"):
        data_url = image_path_or_url
    else:
        data_url = image_to_data_url(image_path_or_url)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    })

    # DeepSeek vision works with deepseek-chat or designated multimodal models
    target_model = model.split(" ")[0] if model else "deepseek-chat"
    # If the user selected a pure reasoning model like deepseek-reasoner that doesn't accept images,
    # route vision queries to deepseek-chat
    if "reasoner" in target_model.lower():
        target_model = "deepseek-chat"

    resp = client.chat.completions.create(
        model=target_model,
        messages=messages,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""
