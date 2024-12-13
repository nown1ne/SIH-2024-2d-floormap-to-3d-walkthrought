from flask import Flask, request, jsonify, render_template, send_file
import os
from werkzeug.utils import secure_filename
import shutil
import uuid
import json
from PIL import Image
import subprocess
import platform

app = Flask(__name__)

# Configuration for uploads and server behavior
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'output'
BEHAVIOR_PACK_PATH = r"C:\\Users\\hp\\AppData\\Local\\Packages\\Microsoft.MinecraftUWP_8wekyb3d8bbwe\\LocalState\\games\\com.mojang\\behavior_packs"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER

# Configuration for the structure
CONFIG = {
    "floor_height": 4,
    "door_height": 2,
    "wall_block": "minecraft:stone",
    "glass_block": "minecraft:light_blue_stained_glass",
    "door_block": "minecraft:oak_door",
    "air_block": "minecraft:air",
    "ceiling_block": "minecraft:ochre_froglight",
}

COLOR_CODES = {
    "blue": (0, 0, 255),
    "red": (255, 0, 0),
    "white": (255, 255, 255),
    "green": (0, 255, 0),
    "purple": (255, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "brown": (156, 90, 60),
}
COLOR_TOLERANCE = 20

# Utility functions

def generate_uuid():
    return str(uuid.uuid4())

def is_color_match(pixel, target_color, tolerance):
    return all(abs(pixel[i] - target_color[i]) <= tolerance for i in range(3))

def parse_image_to_grid(image_path):
    img = Image.open(image_path).convert("RGB")
    return [[tuple(img.getpixel((x, y))) for x in range(img.width)] for y in range(img.height)]

def get_next_structure_number(base_path):
    existing_folders = [f for f in os.listdir(base_path) if f.startswith("structure") and f[9:].isdigit()]
    existing_numbers = [int(f[9:]) for f in existing_folders]
    return max(existing_numbers, default=5) + 1

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    # Get form data
    wall_height = int(request.form.get('wall_height', CONFIG['floor_height']))
    door_height = int(request.form.get('door_height', CONFIG['door_height']))
    generate_ceiling = 'generate_ceiling' in request.form  # Checkbox is present if checked

    # Save uploaded files
    files = request.files.getlist('floor_maps')
    if not files:
        return jsonify({"error": "No files uploaded."}), 400

    floor_files = []
    for file in files:
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        floor_files.append(file_path)

    # Update config with user input
    CONFIG['floor_height'] = wall_height
    CONFIG['door_height'] = door_height
    CONFIG['generate_ceiling'] = generate_ceiling

    # Generate Minecraft function file
    commands = generate_minecraft_commands(floor_files, CONFIG, generate_ceiling)
    mcfunction_path = os.path.join(app.config['OUTPUT_FOLDER'], 'building.mcfunction')
    os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)
    with open(mcfunction_path, "w") as f:
        f.writelines(commands)

    # Create behavior pack
    structure_number = get_next_structure_number(BEHAVIOR_PACK_PATH)
    behavior_pack_name = f"structure{structure_number}"
    create_behavior_pack_structure(BEHAVIOR_PACK_PATH, behavior_pack_name, mcfunction_path)

    # Automatically send the mcfunction file for download
    return send_file(mcfunction_path, as_attachment=True, download_name='building.mcfunction')



@app.route('/download/<pack_name>', methods=['GET'])
def download(pack_name):
    folder_path = os.path.join(BEHAVIOR_PACK_PATH, pack_name)
    if not os.path.exists(folder_path):
        return jsonify({"error": "Behavior pack not found."}), 404

    zip_path = os.path.join(app.config['OUTPUT_FOLDER'], f"{pack_name}.zip")
    shutil.make_archive(zip_path.replace('.zip', ''), 'zip', folder_path)

    return send_file(zip_path, as_attachment=True)

def generate_minecraft_commands(floor_files, config, generate_ceiling):
    """
    Generate Minecraft commands for multiple floors based on the input files.
    This version places light blocks only on white pixels.
    Skips ceiling generation if only one file is uploaded unless generate_ceiling is True.
    """
    commands = ["# Minecraft building generation commands\n"]

    floor_height = config["floor_height"]
    door_height = config["door_height"]
    wall_block = "minecraft:black_stained_glass"
    glass_block = config["glass_block"]
    door_block = config["door_block"]
    ceiling_block = "minecraft:light_gray_stained_glass"
    light_block = "minecraft:light_block"

    for floor_index, file in enumerate(floor_files):
        print(f"Processing floor {floor_index + 1} using file {file}")
        grid = parse_image_to_grid(file)
        floor_base_y = floor_index * floor_height
        ceiling_y = floor_base_y + floor_height - 1

        structure_columns = set()
        structure_rows = set()
        ceiling_holes = set()

        for y, row in enumerate(grid):
            for x, pixel in enumerate(row):
                if is_color_match(pixel, COLOR_CODES["green"], COLOR_TOLERANCE):  # Green: Hole in ceiling
                    ceiling_holes.add((x, y))
                    commands.append(f"fill ~{x} ~{floor_base_y} ~{y} ~{x} ~{ceiling_y - 1} ~{y} {config['air_block']}\n")
                    continue

                if is_color_match(pixel, COLOR_CODES["white"], COLOR_TOLERANCE):  # White: Place light block
                    commands.append(f"setblock ~{x} ~{floor_base_y} ~{y} {light_block} 15\n")
                    continue

                structure_columns.add(x)
                structure_rows.add(y)

                # Handle other colored pixels (like blue for glass, red for doors, etc.)
                if is_color_match(pixel, COLOR_CODES["blue"], COLOR_TOLERANCE):  # Blue: Glass + Wall
                    center_height = floor_base_y + floor_height // 2
                    commands.append(f"fill ~{x} ~{floor_base_y} ~{y} ~{x} ~{center_height - 2} ~{y} {wall_block}\n")
                    commands.append(f"fill ~{x} ~{center_height + 1} ~{y} ~{x} ~{ceiling_y - 1} ~{y} {wall_block}\n")
                    commands.append(f"setblock ~{x} ~{center_height - 1} ~{y} {glass_block}\n")
                    commands.append(f"setblock ~{x} ~{center_height} ~{y} {glass_block}\n")
                elif is_color_match(pixel, COLOR_CODES["red"], COLOR_TOLERANCE):  # Red: Door
                    commands.append(f"setblock ~{x} ~{floor_base_y} ~{y} {door_block}[half=lower,facing=north]\n")
                    commands.append(f"setblock ~{x} ~{floor_base_y + 1} ~{y} {door_block}[half=upper,facing=north]\n")
                    commands.append(f"fill ~{x} ~{floor_base_y + door_height} ~{y} ~{x} ~{ceiling_y - 1} ~{y} {wall_block}\n")
                elif is_color_match(pixel, COLOR_CODES["purple"], COLOR_TOLERANCE):  # Purple: Height - 1 (Wall on 2 blocks)
                    commands.append(f"fill ~{x} ~{floor_base_y} ~{y} ~{x} ~{floor_base_y + 2} ~{y} {wall_block}\n")
                elif is_color_match(pixel, COLOR_CODES["yellow"], COLOR_TOLERANCE):  # Yellow: Height - 2 (Wall on 1 block)
                    commands.append(f"fill ~{x} ~{floor_base_y} ~{y} ~{x} ~{floor_base_y + 1} ~{y} {wall_block}\n")
                elif is_color_match(pixel, COLOR_CODES["cyan"], COLOR_TOLERANCE):  # Cyan: Height - 3 (Wall directly)
                    commands.append(f"setblock ~{x} ~{floor_base_y} ~{y} {wall_block}\n")
                elif is_color_match(pixel, COLOR_CODES["brown"], COLOR_TOLERANCE):  
                    commands.append(f"setblock ~{x} ~{floor_base_y} ~{y} {wall_block}\n")

                else:  # Default: Walls (No light block, no air block)
                    commands.append(f"fill ~{x} ~{floor_base_y} ~{y} ~{x} ~{ceiling_y - 1} ~{y} {wall_block}\n")

        # Find min and max of structure columns and rows to create precise ceiling
        if (len(floor_files) > 1 or generate_ceiling) and structure_columns and structure_rows:  # Add ceiling for single file if generate_ceiling is True
            min_x, max_x = min(structure_columns), max(structure_columns)
            min_y, max_y = min(structure_rows), max(structure_rows)

            # Add ceiling only over the structure area, excluding specific colors
            for x in range(min_x, max_x + 1):
                for y in range(min_y, max_y + 1):
                    if (x, y) not in ceiling_holes and not any(
                        is_color_match(grid[y][x], COLOR_CODES[color], COLOR_TOLERANCE)
                        for color in ["purple", "yellow", "cyan"]
                    ):
                        commands.append(f"setblock ~{x} ~{ceiling_y} ~{y} {ceiling_block}\n")

    return commands


def launch_minecraft():
    """
    Launch Minecraft based on the operating system.
    """
    try:
        system = platform.system().lower()
        
        if system == "windows":
            # Path for Minecraft UWP (Windows Store version)
            minecraft_path = r"shell:AppsFolder\Microsoft.MinecraftUWP_8wekyb3d8bbwe!App"
            subprocess.Popen(f'start {minecraft_path}', shell=True)
        elif system == "darwin":  # macOS
            subprocess.Popen(["open", "-a", "Minecraft"])
        elif system == "linux":
            # Common Minecraft launcher paths or commands
            launchers = [
                "minecraft-launcher",
                "~/Games/minecraft-launcher/minecraft-launcher",
                "/usr/bin/minecraft-launcher"
            ]
            
            for launcher in launchers:
                try:
                    subprocess.Popen([launcher])
                    break
                except FileNotFoundError:
                    continue
        else:
            print(f"Unsupported operating system: {system}")
    except Exception as e:
        print(f"Error launching Minecraft: {e}")


def create_behavior_pack_structure(base_path, folder_name, mcfunction_file):
    folder_path = os.path.join(base_path, folder_name)
    os.makedirs(folder_path, exist_ok=True)
    os.makedirs(os.path.join(folder_path, "functions"), exist_ok=True)
    shutil.copy(mcfunction_file, os.path.join(folder_path, "functions", f"{folder_name}.mcfunction"))
    create_manifest(folder_name, folder_path)
    launch_minecraft()
    

def create_manifest(folder_name, output_path):
    manifest = {
        "header": {
            "version": [0, 0, 1],
            "name": folder_name,
            "description": "",
            "uuid": generate_uuid()
        },
        "modules": [
            {
                "version": [0, 0, 1],
                "type": "data",
                "description": "",
                "uuid": generate_uuid()
            }
        ],
        "format_version": 1
    }
    with open(os.path.join(output_path, "manifest.json"), "w") as file:
        json.dump(manifest, file, indent=2)

if __name__ == '__main__':
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    
    app.run(debug=True)
