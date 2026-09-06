import cv2
import numpy as np
import io
from PIL import Image

def generate_test_crop(vegetable_name: str, target_area: int):
    """
    Generates a synthetic vegetable test image with a specific contour area.
    """
    canvas = np.full((600, 600, 3), 245, dtype=np.uint8) # light background
    
    # Calculate circle/ellipse radius to roughly match target_area (pi * r1 * r2 = target_area)
    r = int(np.sqrt(target_area / np.pi))
    center = (300, 300)
    
    colors = {
        "Tomato": (30, 30, 220),    # Red in BGR
        "Potato": (90, 150, 190),   # Brownish-gold in BGR
        "Carrot": (20, 120, 240),   # Orange in BGR
        "Onion": (120, 50, 160),    # Red/purple onion in BGR
        "Garlic": (210, 225, 230)   # Creamy white in BGR
    }
    
    color = colors.get(vegetable_name, (100, 100, 100))
    
    if vegetable_name == "Carrot":
        # Draw conical/elliptical shape
        axes = (int(r * 0.6), int(r * 1.6))
        cv2.ellipse(canvas, center, axes, 30, 0, 360, color, -1)
    else:
        axes = (int(r * 1.1), int(r * 0.9))
        cv2.ellipse(canvas, center, axes, 15, 0, 360, color, -1)
        
    # Add some texture/noise so it feels like a real surface
    noise = np.random.randint(-15, 15, canvas.shape, dtype=np.int16)
    canvas = np.clip(canvas.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    
    _, buffer = cv2.imencode('.jpg', canvas)
    return buffer.tobytes()

if __name__ == "__main__":
    from main import CropQualityGrader
    
    print("Testing CropQualityGrader with different crops and surface areas:")
    
    tests = [
        ("Tomato", 12000, "Average"),
        ("Tomato", 25000, "Medium"),
        ("Tomato", 42000, "Good"),
        ("Potato", 10000, "Average"),
        ("Onion", 28000, "Medium"),
        ("Garlic", 14000, "Average"),
        ("Carrot", 38000, "Good")
    ]
    
    for veg, target_area, expected_quality in tests:
        img_bytes = generate_test_crop(veg, target_area)
        result = CropQualityGrader.grade(img_bytes)
        print(f"Target: {veg} ({target_area} px, Expected: {expected_quality}) -> Got: {result}")
        assert result["quality"] == expected_quality, f"Expected {expected_quality}, got {result['quality']}"
        assert result["vegetable"] in CropQualityGrader.TARGET_VEGETABLES
    
    print("\nAll unit tests passed successfully!")
