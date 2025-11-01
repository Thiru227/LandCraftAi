import os
import json
import base64
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session
import google.generativeai as genai
import trimesh
import numpy as np
from io import BytesIO
import requests

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/generated'
app.config['DATABASE'] = 'landcraft.db'
app.secret_key = os.environ.get('SECRET_KEY', 'landcraft-secret-key-change-in-production')

# API Keys
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', 'YOUR_GEMINI_KEY')
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', 'YOUR_OPENROUTER_KEY')

genai.configure(api_key=GEMINI_API_KEY)

# Try to import districts module, fallback if not available
try:
    from districts import get_rate_for_pincode, get_district_for_pincode
    HAS_DISTRICTS_MODULE = True
except ImportError:
    HAS_DISTRICTS_MODULE = False
    print("Warning: districts module not found, using fallback rates")

# Pincode rates - fallback and backward compatibility
PINCODE_RATES = {
    "600001": 1800, "600002": 1750, "600003": 1700,
    "641001": 1500, "641002": 1480, "641035": 1500,
    "620001": 1400, "620002": 1380, "620003": 1350,
    "636001": 1300, "636002": 1280, "636003": 1250,
    "630001": 1200, "630002": 1180, "630003": 1150
}

# Smart chip suggestions
SMART_CHIPS = {
    "initial": [
        "Modern minimalist design",
        "Traditional Tamil Nadu style",
        "Open kitchen layout",
        "Vastu-compliant design",
        "Add a pooja room",
        "Include a balcony"
    ],
    "rooms": [
        "Master bedroom with attached bathroom",
        "Walk-in closet in master bedroom",
        "Large living room",
        "Separate dining area",
        "Modular kitchen",
        "Study room / home office"
    ],
    "features": [
        "Natural lighting focus",
        "Cross ventilation",
        "Rainwater harvesting setup",
        "Solar panel ready",
        "Garden space",
        "Car parking area"
    ]
}

def init_db():
    """Initialize SQLite database"""
    conn = sqlite3.connect(app.config['DATABASE'])
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bhk INTEGER NOT NULL,
            sqft INTEGER NOT NULL,
            facing TEXT NOT NULL,
            pincode TEXT NOT NULL,
            rate INTEGER NOT NULL,
            cost_estimate INTEGER NOT NULL,
            style TEXT,
            chat_history TEXT,
            final_prompt TEXT,
            glb_file TEXT,
            plan_text TEXT,
            svg_file TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

def call_openrouter(messages, model="anthropic/claude-3.5-sonnet"):
    """Call OpenRouter API for chatbot"""
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": messages
            },
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        else:
            return f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Error calling OpenRouter: {str(e)}"

def build_gemini_prompt_from_conversation(bhk, sqft, facing, style, chat_history):
    """Build structured prompt for Gemini from chat conversation"""
    
    # Extract key details from chat
    conversation_summary = "\n".join([
        f"{msg['role']}: {msg['content']}" 
        for msg in chat_history[-6:]  # Last 6 messages
    ])
    
    prompt = f"""Generate a detailed 3D house plan specification in JSON format.

USER REQUIREMENTS:
- BHK: {bhk}
- Total Area: {sqft} sq ft
- Facing: {facing}
- Style: {style}

CONVERSATION CONTEXT:
{conversation_summary}

Generate a JSON structure with:
{{
  "rooms": [
    {{
      "name": "Master Bedroom",
      "dimensions": {{"length": 14, "width": 12, "height": 10}},
      "position": {{"x": 0, "y": 0, "z": 0}},
      "features": ["attached_bathroom", "balcony"]
    }},
    ...
  ],
  "vastu_compliance": "...",
  "materials": [...],
  "cost_breakdown": {{...}}
}}

Consider:
1. Room proportions for {bhk} BHK
2. {facing} facing Vastu principles
3. User preferences from conversation
4. {style} architectural style
5. Tamil Nadu climate considerations

Return ONLY valid JSON, no explanations."""

    return prompt

def generate_glb_from_json(room_data, bhk, sqft):
    """Generate GLB from structured JSON room data"""
    try:
        scene = trimesh.Scene()
        
        # Color palette (RGB + Alpha)
        room_colors = {
            "bedroom": [200, 150, 150, 255],
            "living": [150, 200, 150, 255],
            "kitchen": [150, 150, 200, 255],
            "bathroom": [200, 200, 150, 255],
            "dining": [180, 150, 200, 255],
            "default": [180, 180, 180, 255]
        }
        
        if isinstance(room_data, dict) and "rooms" in room_data:
            rooms = room_data["rooms"]
        else:
            rooms = None
        
        if rooms:
            for room in rooms:
                dims = room.get("dimensions", {"length": 10, "width": 10, "height": 10})
                pos = room.get("position", {"x": 0, "y": 0, "z": 0})
                
                length = dims.get("length", 10) / 3.28  # Convert ft to meters
                width = dims.get("width", 10) / 3.28
                height = dims.get("height", 10) / 3.28
                
                box = trimesh.creation.box(extents=[length, width, height])
                box.vertices += [pos.get("x", 0), pos.get("y", 0), height/2]
                
                # Set color based on room type
                room_type = room.get("name", "").lower()
                color = room_colors["default"]
                for key in room_colors:
                    if key in room_type:
                        color = room_colors[key]
                        break
                
                box.visual.vertex_colors = color
                scene.add_geometry(box, node_name=room.get("name", "room"))
        else:
            # Better fallback: Create actual house layout
            scene = generate_realistic_house_glb(bhk, sqft)
            return scene.export(file_type='glb')
        
        # Add floor
        max_x = max([r.get("position", {}).get("x", 0) + r.get("dimensions", {}).get("length", 10)/3.28 for r in (rooms or [])] or [10])
        max_y = max([r.get("position", {}).get("y", 0) + r.get("dimensions", {}).get("width", 10)/3.28 for r in (rooms or [])] or [10])
        
        floor = trimesh.creation.box(extents=[max_x + 2, max_y + 2, 0.1])
        floor.vertices += [max_x/2, max_y/2, -0.05]
        floor.visual.vertex_colors = [220, 220, 220, 255]
        scene.add_geometry(floor, node_name="floor")
        
        # Export
        output = BytesIO()
        scene.export(output, file_type='glb')
        output.seek(0)
        return output.getvalue()
        
    except Exception as e:
        print(f"GLB generation error: {e}")
        return generate_realistic_house_glb(bhk, sqft).export(file_type='glb')

def create_furniture(room_type, x, y, z, room_w, room_d):
    """Create furniture meshes for different room types"""
    furniture = []
    
    if "bedroom" in room_type.lower():
        # Bed (centered)
        bed = trimesh.creation.box(extents=[1.8, 2.0, 0.5])
        bed.vertices += [x + room_w/2, y + room_d/2, z + 0.25]
        bed.visual.vertex_colors = [139, 69, 19, 255]  # Brown
        furniture.append(("Bed", bed))
        
        # Nightstand
        nightstand = trimesh.creation.box(extents=[0.4, 0.4, 0.5])
        nightstand.vertices += [x + room_w/2 + 1.2, y + room_d/2, z + 0.25]
        nightstand.visual.vertex_colors = [160, 82, 45, 255]
        furniture.append(("Nightstand", nightstand))
        
    elif "living" in room_type.lower():
        # Sofa
        sofa = trimesh.creation.box(extents=[2.0, 0.8, 0.7])
        sofa.vertices += [x + room_w/2, y + 1.0, z + 0.35]
        sofa.visual.vertex_colors = [70, 130, 180, 255]  # Steel blue
        furniture.append(("Sofa", sofa))
        
        # Coffee table
        table = trimesh.creation.box(extents=[1.0, 0.6, 0.4])
        table.vertices += [x + room_w/2, y + 2.2, z + 0.2]
        table.visual.vertex_colors = [139, 69, 19, 255]
        furniture.append(("Table", table))
        
    elif "kitchen" in room_type.lower():
        # Counter
        counter = trimesh.creation.box(extents=[room_w - 0.5, 0.6, 0.9])
        counter.vertices += [x + room_w/2, y + 0.5, z + 0.45]
        counter.visual.vertex_colors = [192, 192, 192, 255]  # Gray
        furniture.append(("Counter", counter))
        
    elif "dining" in room_type.lower():
        # Dining table
        table = trimesh.creation.box(extents=[1.5, 1.0, 0.75])
        table.vertices += [x + room_w/2, y + room_d/2, z + 0.375]
        table.visual.vertex_colors = [139, 69, 19, 255]
        furniture.append(("Dining_Table", table))
        
    elif "bathroom" in room_type.lower():
        # Toilet
        toilet = trimesh.creation.cylinder(radius=0.25, height=0.4)
        toilet.vertices += [x + 0.5, y + 0.5, z + 0.2]
        toilet.visual.vertex_colors = [255, 255, 255, 255]
        furniture.append(("Toilet", toilet))
    
    return furniture

def create_outdoor_plants(scene, max_x, max_y, z=0):
    """Add plants/trees around the house"""
    plant_positions = [
        (-1.5, 2, "Tree_1"),
        (-1.5, max_y - 2, "Tree_2"),
        (max_x + 1.5, 2, "Tree_3"),
        (max_x + 1.5, max_y - 2, "Tree_4"),
    ]
    
    for px, py, name in plant_positions:
        # Tree trunk
        trunk = trimesh.creation.cylinder(radius=0.15, height=1.5)
        trunk.vertices += [px, py, z + 0.75]
        trunk.visual.vertex_colors = [101, 67, 33, 255]  # Brown
        scene.add_geometry(trunk, node_name=f"{name}_trunk")
        
        # Tree foliage (cone shape)
        foliage = trimesh.creation.cone(radius=0.8, height=1.5)
        foliage.vertices += [px, py, z + 2.25]
        foliage.visual.vertex_colors = [34, 139, 34, 255]  # Forest green
        scene.add_geometry(foliage, node_name=f"{name}_foliage")

def create_internal_walls(scene, rooms, wall_thickness=0.15, wall_height=3, z=0):
    """Create internal walls between rooms"""
    wall_color = [220, 220, 220, 255]  # Light gray
    
    # Create walls between adjacent rooms
    for i, room1 in enumerate(rooms):
        for room2 in rooms[i+1:]:
            r1_x1, r1_y1 = room1["x"], room1["y"]
            r1_x2, r1_y2 = room1["x"] + room1["w"], room1["y"] + room1["d"]
            
            r2_x1, r2_y1 = room2["x"], room2["y"]
            r2_x2, r2_y2 = room2["x"] + room2["w"], room2["y"] + room2["d"]
            
            # Check if rooms share a wall
            # Vertical wall (rooms side by side)
            if abs(r1_x2 - r2_x1) < 0.1 and not (r1_y2 < r2_y1 or r2_y2 < r1_y1):
                overlap_y1 = max(r1_y1, r2_y1)
                overlap_y2 = min(r1_y2, r2_y2)
                if overlap_y2 > overlap_y1:
                    wall = trimesh.creation.box(extents=[wall_thickness, overlap_y2 - overlap_y1, wall_height])
                    wall.vertices += [r1_x2, (overlap_y1 + overlap_y2)/2, z + wall_height/2]
                    wall.visual.vertex_colors = wall_color
                    scene.add_geometry(wall, node_name=f"Wall_internal_{i}_{i+1}")
            
            # Horizontal wall (rooms stacked)
            elif abs(r1_y2 - r2_y1) < 0.1 and not (r1_x2 < r2_x1 or r2_x2 < r1_x1):
                overlap_x1 = max(r1_x1, r2_x1)
                overlap_x2 = min(r1_x2, r2_x2)
                if overlap_x2 > overlap_x1:
                    wall = trimesh.creation.box(extents=[overlap_x2 - overlap_x1, wall_thickness, wall_height])
                    wall.vertices += [(overlap_x1 + overlap_x2)/2, r1_y2, z + wall_height/2]
                    wall.visual.vertex_colors = wall_color
                    scene.add_geometry(wall, node_name=f"Wall_internal_{i}_{i+1}_h")

def generate_realistic_house_glb(bhk, sqft):
    """Generate a realistic 3D house with furniture and landscaping"""
    scene = trimesh.Scene()
    
    # Calculate approximate dimensions
    total_area_m2 = sqft * 0.092903
    side_length = np.sqrt(total_area_m2)
    
    # Define room layouts based on BHK
    if bhk == 1:
        rooms = [
            {"name": "Living Room", "x": 0, "y": 0, "w": 4, "d": 5, "h": 3, "color": [150, 200, 150, 255]},
            {"name": "Bedroom", "x": 4.5, "y": 0, "w": 4, "d": 4, "h": 3, "color": [200, 150, 150, 255]},
            {"name": "Kitchen", "x": 0, "y": 5.5, "w": 3, "d": 3, "h": 3, "color": [150, 150, 200, 255]},
            {"name": "Bathroom", "x": 4.5, "y": 4.5, "w": 2, "d": 2, "h": 3, "color": [200, 200, 150, 255]},
        ]
    elif bhk == 2:
        rooms = [
            {"name": "Living Room", "x": 0, "y": 0, "w": 5, "d": 4, "h": 3, "color": [150, 200, 150, 255]},
            {"name": "Bedroom 1", "x": 5.5, "y": 0, "w": 4, "d": 4, "h": 3, "color": [200, 150, 150, 255]},
            {"name": "Bedroom 2", "x": 10, "y": 0, "w": 3.5, "d": 4, "h": 3, "color": [200, 150, 150, 255]},
            {"name": "Kitchen", "x": 0, "y": 4.5, "w": 3, "d": 3.5, "h": 3, "color": [150, 150, 200, 255]},
            {"name": "Bathroom", "x": 3.5, "y": 4.5, "w": 2, "d": 2.5, "h": 3, "color": [200, 200, 150, 255]},
            {"name": "Dining", "x": 6, "y": 4.5, "w": 3, "d": 3, "h": 3, "color": [180, 150, 200, 255]},
        ]
    elif bhk == 3:
        rooms = [
            {"name": "Living Room", "x": 0, "y": 0, "w": 5, "d": 5, "h": 3, "color": [150, 200, 150, 255]},
            {"name": "Bedroom 1", "x": 5.5, "y": 0, "w": 4, "d": 4, "h": 3, "color": [200, 150, 150, 255]},
            {"name": "Bedroom 2", "x": 10, "y": 0, "w": 3.5, "d": 4, "h": 3, "color": [200, 150, 150, 255]},
            {"name": "Bedroom 3", "x": 0, "y": 5.5, "w": 3.5, "d": 4, "h": 3, "color": [200, 150, 150, 255]},
            {"name": "Kitchen", "x": 4, "y": 5.5, "w": 3, "d": 3, "h": 3, "color": [150, 150, 200, 255]},
            {"name": "Bathroom 1", "x": 7.5, "y": 5.5, "w": 2, "d": 2, "h": 3, "color": [200, 200, 150, 255]},
            {"name": "Bathroom 2", "x": 10, "y": 5.5, "w": 2, "d": 2, "h": 3, "color": [200, 200, 150, 255]},
            {"name": "Dining", "x": 4, "y": 9, "w": 3.5, "d": 3, "h": 3, "color": [180, 150, 200, 255]},
        ]
    else:  # 4 BHK
        rooms = [
            {"name": "Living Room", "x": 0, "y": 0, "w": 6, "d": 5, "h": 3, "color": [150, 200, 150, 255]},
            {"name": "Bedroom 1", "x": 6.5, "y": 0, "w": 4, "d": 4.5, "h": 3, "color": [200, 150, 150, 255]},
            {"name": "Bedroom 2", "x": 11, "y": 0, "w": 4, "d": 4, "h": 3, "color": [200, 150, 150, 255]},
            {"name": "Bedroom 3", "x": 0, "y": 5.5, "w": 4, "d": 4, "h": 3, "color": [200, 150, 150, 255]},
            {"name": "Bedroom 4", "x": 4.5, "y": 5.5, "w": 3.5, "d": 4, "h": 3, "color": [200, 150, 150, 255]},
            {"name": "Kitchen", "x": 8.5, "y": 5.5, "w": 3.5, "d": 3, "h": 3, "color": [150, 150, 200, 255]},
            {"name": "Bathroom 1", "x": 12.5, "y": 5.5, "w": 2, "d": 2, "h": 3, "color": [200, 200, 150, 255]},
            {"name": "Bathroom 2", "x": 0, "y": 10, "w": 2, "d": 2, "h": 3, "color": [200, 200, 150, 255]},
            {"name": "Dining", "x": 2.5, "y": 10, "w": 4, "d": 3.5, "h": 3, "color": [180, 150, 200, 255]},
        ]
    
    # Create room boxes with lower height (no ceiling visible)
    for room in rooms:
        # Floor for each room
        room_floor = trimesh.creation.box(extents=[room["w"], room["d"], 0.05])
        room_floor.vertices += [room["x"] + room["w"]/2, room["y"] + room["d"]/2, 0.025]
        room_floor.visual.vertex_colors = [245, 245, 220, 255]  # Beige floor
        scene.add_geometry(room_floor, node_name=f"{room['name']}_floor")
        
        # Add furniture
        furniture_items = create_furniture(room["name"], room["x"], room["y"], 0.05, room["w"], room["d"])
        for furn_name, furn_mesh in furniture_items:
            scene.add_geometry(furn_mesh, node_name=f"{room['name']}_{furn_name}")
    
    # Calculate building dimensions
    max_x = max([r["x"] + r["w"] for r in rooms])
    max_y = max([r["y"] + r["d"] for r in rooms])
    
    # Add ground/foundation (larger than building)
    ground = trimesh.creation.box(extents=[max_x + 4, max_y + 4, 0.1])
    ground.vertices += [max_x/2, max_y/2, -0.05]
    ground.visual.vertex_colors = [144, 238, 144, 255]  # Light green grass
    scene.add_geometry(ground, node_name="Ground")
    
    # Add outer walls (higher and thicker)
    wall_thickness = 0.25
    wall_height = 3.5
    wall_color = [210, 180, 140, 255]  # Tan/beige exterior
    
    # North wall
    north_wall = trimesh.creation.box(extents=[max_x + wall_thickness, wall_thickness, wall_height])
    north_wall.vertices += [max_x/2, -wall_thickness/2, wall_height/2]
    north_wall.visual.vertex_colors = wall_color
    scene.add_geometry(north_wall, node_name="Wall_North")
    
    # South wall
    south_wall = trimesh.creation.box(extents=[max_x + wall_thickness, wall_thickness, wall_height])
    south_wall.vertices += [max_x/2, max_y + wall_thickness/2, wall_height/2]
    south_wall.visual.vertex_colors = wall_color
    scene.add_geometry(south_wall, node_name="Wall_South")
    
    # East wall
    east_wall = trimesh.creation.box(extents=[wall_thickness, max_y, wall_height])
    east_wall.vertices += [-wall_thickness/2, max_y/2, wall_height/2]
    east_wall.visual.vertex_colors = wall_color
    scene.add_geometry(east_wall, node_name="Wall_East")
    
    # West wall
    west_wall = trimesh.creation.box(extents=[wall_thickness, max_y, wall_height])
    west_wall.vertices += [max_x + wall_thickness/2, max_y/2, wall_height/2]
    west_wall.visual.vertex_colors = wall_color
    scene.add_geometry(west_wall, node_name="Wall_West")
    
    # Add internal walls between rooms
    create_internal_walls(scene, rooms, wall_thickness=0.15, wall_height=wall_height)
    
    # Add outdoor landscaping
    create_outdoor_plants(scene, max_x, max_y)
    
    # Add a simple pathway/driveway
    driveway = trimesh.creation.box(extents=[2, max_y + 4, 0.08])
    driveway.vertices += [-2, max_y/2, 0.04]
    driveway.visual.vertex_colors = [128, 128, 128, 255]  # Gray concrete
    scene.add_geometry(driveway, node_name="Driveway")
    
    return scene

def generate_svg_floor_plan(bhk, sqft):
    """Generate SVG floor plan"""
    width = 800
    height = 600
    
    rooms = []
    if bhk == 1:
        rooms = [
            {"name": "Living", "x": 50, "y": 50, "w": 300, "h": 250},
            {"name": "Bedroom", "x": 400, "y": 50, "w": 300, "h": 250},
            {"name": "Kitchen", "x": 50, "y": 350, "w": 200, "h": 150},
            {"name": "Bathroom", "x": 300, "y": 350, "w": 150, "h": 150}
        ]
    elif bhk == 2:
        rooms = [
            {"name": "Living", "x": 50, "y": 50, "w": 250, "h": 200},
            {"name": "Bedroom 1", "x": 350, "y": 50, "w": 200, "h": 200},
            {"name": "Bedroom 2", "x": 600, "y": 50, "w": 200, "h": 200},
            {"name": "Kitchen", "x": 50, "y": 300, "w": 180, "h": 150},
            {"name": "Bathroom", "x": 280, "y": 300, "w": 150, "h": 150}
        ]
    elif bhk == 3:
        rooms = [
            {"name": "Living", "x": 50, "y": 50, "w": 220, "h": 180},
            {"name": "Bedroom 1", "x": 320, "y": 50, "w": 180, "h": 180},
            {"name": "Bedroom 2", "x": 550, "y": 50, "w": 180, "h": 180},
            {"name": "Bedroom 3", "x": 50, "y": 280, "w": 180, "h": 180},
            {"name": "Kitchen", "x": 280, "y": 280, "w": 150, "h": 130},
            {"name": "Bath 1", "x": 480, "y": 280, "w": 120, "h": 130}
        ]
    else:
        rooms = [
            {"name": "Living", "x": 50, "y": 50, "w": 200, "h": 150},
            {"name": "Dining", "x": 300, "y": 50, "w": 150, "h": 150},
            {"name": "BR 1", "x": 500, "y": 50, "w": 150, "h": 150},
            {"name": "BR 2", "x": 700, "y": 50, "w": 150, "h": 150},
            {"name": "BR 3", "x": 50, "y": 250, "w": 150, "h": 150},
            {"name": "Kitchen", "x": 250, "y": 250, "w": 150, "h": 130}
        ]
    
    svg = f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
    svg += '<rect width="100%" height="100%" fill="#f5f5f5"/>'
    
    for room in rooms:
        svg += f'<rect x="{room["x"]}" y="{room["y"]}" width="{room["w"]}" height="{room["h"]}" fill="white" stroke="#333" stroke-width="2"/>'
        text_x = room["x"] + room["w"] // 2
        text_y = room["y"] + room["h"] // 2
        svg += f'<text x="{text_x}" y="{text_y}" text-anchor="middle" font-size="14" fill="#333">{room["name"]}</text>'
    
    svg += '</svg>'
    return svg

@app.route('/logo.jpeg')
def logo_asset():
    """Serve the site logo placed at project root."""
    logo_path = os.path.join(os.path.dirname(__file__), 'logo.jpeg')
    if os.path.exists(logo_path):
        return send_file(logo_path, mimetype='image/jpeg')
    return "Logo not found", 404

@app.route('/')
def index():
    """Homepage"""
    return render_template('index.html')

@app.route('/calculate-rate', methods=['POST'])
def calculate_rate():
    """Calculate construction rate based on inputs"""
    data = request.json
    
    plot_size = float(data.get('plot_size', 1000))
    unit = data.get('unit', 'sqft')
    pincode = data.get('pincode', '641035')
    
    # Convert to sqft
    if unit == 'sqm':
        sqft = int(plot_size * 10.764)
    elif unit == 'cent':
        sqft = int(plot_size * 435.6)
    else:
        sqft = int(plot_size)
    
    # Try districts module first, fallback to old dict
    if HAS_DISTRICTS_MODULE:
        rate = get_rate_for_pincode(pincode)
        district = get_district_for_pincode(pincode)
    else:
        rate = PINCODE_RATES.get(pincode, 1500)
        district = "Unknown"
    
    cost_estimate = sqft * rate
    
    return jsonify({
        'sqft': sqft,
        'rate': rate,
        'cost_estimate': cost_estimate,
        'formatted_cost': f"₹{cost_estimate:,}",
        'district': district
    })

@app.route('/chat', methods=['POST'])
def chat():
    """Handle chatbot conversation"""
    data = request.json
    user_message = data.get('message', '')
    chat_history = session.get('chat_history', [])
    user_params = session.get('user_params', {})
    
    # Add user message
    chat_history.append({"role": "user", "content": user_message})
    
    # Build system context
    system_prompt = f"""You are a helpful house planning assistant for Landcraft. 
    
User wants to build a {user_params.get('bhk', 2)} BHK house with {user_params.get('sqft', 1000)} sqft area, {user_params.get('facing', 'East')} facing.
Estimated cost: ₹{user_params.get('cost_estimate', 0):,}

Your job:
1. Ask clarifying questions about room preferences
2. Understand their style and functional needs
3. Suggest smart improvements
4. Keep responses concise (2-3 sentences max)
5. After gathering enough info, say "Ready to generate your house plan!"

Current conversation context available. Be conversational and helpful."""
    
    # Prepare messages for OpenRouter
    messages = [
        {"role": "system", "content": system_prompt}
    ] + chat_history
    
    # Get response from OpenRouter
    bot_response = call_openrouter(messages)
    
    # Add bot response
    chat_history.append({"role": "assistant", "content": bot_response})
    
    # Update session
    session['chat_history'] = chat_history
    
    # Determine smart chips based on conversation
    chips = SMART_CHIPS['initial']
    if len(chat_history) > 4:
        chips = SMART_CHIPS['features']
    elif len(chat_history) > 2:
        chips = SMART_CHIPS['rooms']
    
    # Check if ready to generate
    ready_to_generate = "ready to generate" in bot_response.lower() or len(chat_history) > 8
    
    return jsonify({
        'response': bot_response,
        'smart_chips': chips,
        'ready_to_generate': ready_to_generate
    })

@app.route('/init-chat', methods=['POST'])
def init_chat():
    """Initialize chat session with user parameters"""
    data = request.json
    
    bhk = int(data.get('bhk', 2))
    sqft = int(data.get('sqft', 1000))
    facing = data.get('facing', 'East')
    style = data.get('style', 'Modern')
    pincode = data.get('pincode', '641035')
    
    # Get rate using districts module if available
    if HAS_DISTRICTS_MODULE:
        rate = get_rate_for_pincode(pincode)
    else:
        rate = PINCODE_RATES.get(pincode, 1500)
    
    cost_estimate = sqft * rate
    
    # Store in session
    session['user_params'] = {
        'bhk': bhk,
        'sqft': sqft,
        'facing': facing,
        'style': style,
        'pincode': pincode,
        'rate': rate,
        'cost_estimate': cost_estimate
    }
    
    session['chat_history'] = []
    
    # Initial bot message
    initial_message = f"""Great! I'll help you design your {bhk} BHK house ({sqft} sqft, {facing} facing).

What's most important to you? Room sizes, natural lighting, privacy, or something else?"""
    
    session['chat_history'].append({
        "role": "assistant", 
        "content": initial_message
    })
    
    return jsonify({
        'message': initial_message,
        'smart_chips': SMART_CHIPS['initial']
    })

@app.route('/generate-final', methods=['POST'])
def generate_final():
    """Generate final house plan and GLB"""
    try:
        user_params = session.get('user_params', {})
        chat_history = session.get('chat_history', [])
        
        bhk = user_params['bhk']
        sqft = user_params['sqft']
        facing = user_params['facing']
        style = user_params.get('style', 'Modern')
        cost_estimate = user_params['cost_estimate']
        pincode = user_params['pincode']
        rate = user_params['rate']
        
        # Build Gemini prompt from conversation
        gemini_prompt = build_gemini_prompt_from_conversation(
            bhk, sqft, facing, style, chat_history
        )
        
        # Call Gemini
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        
        try:
            response = model.generate_content(gemini_prompt)
            plan_json = json.loads(response.text)
            plan_text = json.dumps(plan_json, indent=2)
        except:
            # Fallback text plan
            plan_text = f"{bhk} BHK House Plan\nArea: {sqft} sqft\nFacing: {facing}\nStyle: {style}\n\nBased on your conversation, we've designed a custom layout."
            plan_json = None
        
        # Generate GLB
        if plan_json:
            glb_data = generate_glb_from_json(plan_json, bhk, sqft)
        else:
            glb_scene = generate_realistic_house_glb(bhk, sqft)
            output = BytesIO()
            glb_scene.export(output, file_type='glb')
            output.seek(0)
            glb_data = output.getvalue()
        
        # Generate SVG
        svg_content = generate_svg_floor_plan(bhk, sqft)
        
        # Save files
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        glb_filename = f"house_{timestamp}.glb"
        glb_path = os.path.join(app.config['UPLOAD_FOLDER'], glb_filename)
        with open(glb_path, 'wb') as f:
            f.write(glb_data)
        
        svg_filename = f"plan_{timestamp}.svg"
        svg_path = os.path.join(app.config['UPLOAD_FOLDER'], svg_filename)
        with open(svg_path, 'w') as f:
            f.write(svg_content)
        
        # Save to database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO requests 
            (bhk, sqft, facing, pincode, rate, cost_estimate, style, chat_history, final_prompt, glb_file, plan_text, svg_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (bhk, sqft, facing, pincode, rate, cost_estimate, style, 
              json.dumps(chat_history), gemini_prompt, glb_filename, plan_text, svg_filename))
        conn.commit()
        request_id = cursor.lastrowid
        conn.close()
        
        # Clear session
        session.pop('chat_history', None)
        session.pop('user_params', None)
        
        return jsonify({
            'success': True,
            'request_id': request_id,
            'redirect_url': f'/results/{request_id}'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/results/<int:request_id>')
def results(request_id):
    """Display results"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM requests WHERE id = ?', (request_id,))
    req = cursor.fetchone()
    conn.close()
    
    if not req:
        return "Request not found", 404
    
    return render_template('results.html',
                         request_id=req['id'],
                         bhk=req['bhk'],
                         sqft=req['sqft'],
                         facing=req['facing'],
                         style=req['style'],
                         cost_estimate=req['cost_estimate'],
                         plan_text=req['plan_text'],
                         svg_file=req['svg_file'],
                         glb_file=req['glb_file'])

@app.route('/glb/<int:request_id>')
def serve_glb(request_id):
    """Serve GLB file"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT glb_file FROM requests WHERE id = ?', (request_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        glb_path = os.path.join(app.config['UPLOAD_FOLDER'], result['glb_file'])
        return send_file(glb_path, mimetype='model/gltf-binary')
    return "Not found", 404
@app.route('/vr')
def vr():
    return render_template('vr.html')
@app.route('/admin')
def admin():
    """Admin dashboard"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM requests ORDER BY created_at DESC LIMIT 50')
    requests = cursor.fetchall()
    conn.close()
    
    return render_template('admin.html', requests=requests)

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)