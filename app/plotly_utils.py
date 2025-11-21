# app/plotly_utils.py
from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional
import plotly.io as pio
import plotly.graph_objects as go

logger = logging.getLogger(__name__)

def safe_write_plotly_image(fig: "go.Figure", out_path: str, format: str = "png", scale: int = 2) -> Optional[str]:
    """
    Attempt to export a Plotly figure to an image file.

    Tries multiple methods (fig.write_image and pio.to_image). Returns the out_path
    on success, or None on failure. Does not raise exceptions.

    Parameters:
    - fig: plotly.graph_objects.Figure
    - out_path: destination file path (string)
    - format: image format (png, jpeg, svg, etc.)
    - scale: scale multiplier for resolution
    """
    try:
        # Primary: use figure method
        fig.write_image(str(out_path), format=format, scale=scale)
        return str(out_path)
    except Exception as exc1:
        logger.debug("fig.write_image failed: %s", exc1)
        # Secondary: try pio.to_image
        try:
            img_bytes = pio.to_image(fig, format=format, scale=scale)
            with open(out_path, "wb") as fh:
                fh.write(img_bytes)
            return str(out_path)
        except Exception as exc2:
            logger.debug("pio.to_image failed: %s", exc2)
            return None
