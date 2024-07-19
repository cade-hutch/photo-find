import os
import json
import pickle
import faiss
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PIL import Image
from openai import OpenAI
from langchain_community.embeddings import OpenAIEmbeddings

MAIN_DIR = os.path.dirname(os.path.realpath(__file__))
DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), 'data')
EMBEDDINGS_DIR = os.path.join(MAIN_DIR, 'embeddings')

DESCR_FILENAME = "descriptions.json"

_10_MB = 10*1024*1024
_5_MB = 5*1024*1024
_3_MB = 3*1024*1024


def validate_openai_api_key(openai_api_key):
    validate = False
    if not openai_api_key.startswith('sk-'):
        openai_api_key = 'sk-' + openai_api_key
    client = OpenAI(api_key=openai_api_key)
    try:
        response = client.chat.completions.create(
            model='gpt-3.5-turbo',
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=2
        )
        if response.choices[0].message.content:
            validate = True
    #TODO: error code for invalid key is 401
    except Exception as e:
        print(f"An error occurred: {e}")
    # reattempt with 'sk-proj-' prefix
    if not validate:
        openai_api_key = 'sk-proj-' + openai_api_key[3:]
        try:
            response = client.chat.completions.create(
                model='gpt-3.5-turbo',
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=2
            )
            if response.choices[0].message.content:
                validate = True
        except Exception as e:
            print(f"An error occurred: {e}")
            return False
    
    return validate


# ****** FILE UTILS ******

#TODO: not currently used
def are_all_files_png_and_jpg(directory_path):
    for filename in os.listdir(directory_path):
        file_path = os.path.join(directory_path, filename)

        if os.path.isfile(file_path) and not filename.lower().endswith((".png", ".jpg")):
            if not filename.endswith('.DS_Store'):
                print('invalid folder: contains files that are not pngs/jpgs')
                return False
    return True


#TODO: not currently used
def descriptions_file_up_to_date(images_dir, json_file_path):
    json_file_names = []
    with open(json_file_path, 'r') as file:
        data = json.load(file)
        for element in data:
            if 'file_name' in element:
                json_file_names.append(element['file_name'])
    
    img_names = []
    for entry in os.listdir(images_dir):
        # Construct the full path of the entry
        full_path = os.path.join(images_dir, entry)
        # Check if the entry is a file and has a .png extension
        if os.path.isfile(full_path) and entry.lower().endswith((".png", ".jpg")):
            img_names.append(entry)

    if len(img_names) != len(json_file_names):
        return False
    
    return sorted(json_file_names) == sorted(img_names)


#TODO: not currently used
def get_descriptions_from_json(json_description_file_path, get_images=False):
    #return str list(s)
    try:
        with open(json_description_file_path, 'r') as file:
            data = json.load(file)
    except FileNotFoundError:
        data = []

    descriptions = []
    image_names = []
    if get_images:
        for element in data:
            descriptions.append(element['description'])
            image_names.append(element['file_name'])

        return image_names, descriptions
    else:
        for element in data:
            descriptions.append(element['description'])
        return descriptions


def retrieve_contents_from_json(json_file_path):
    #return list of dicts(keys = filename, value = descr)
    try:
        with open(json_file_path, 'r') as file:
            data = json.load(file)
            return data
    except FileNotFoundError:
        print(f"File not found: {json_file_path}")
        return None
    except json.JSONDecodeError:
        print(f"Error decoding JSON file: {json_file_path}")
        return None


#TODO: not currently used
def get_new_descriptions(new_images, json_description_file_path):
    ...


def get_image_count(images_dir):
    images_count = 0
    for file in os.listdir(images_dir):
        if file.endswith((".png", ".jpg")):
            images_count += 1
    return images_count


def get_descr_filepath(images_dir):
    key_base_dir = os.path.dirname(images_dir)
    json_description_file_path = os.path.join(key_base_dir, DESCR_FILENAME)

    return json_description_file_path


# ****** IMAGE PROCESSING UTILS ******

def reduce_png_quality(file_path, output_path, quality_level=50, max_size=_3_MB, scale_factor=0.6):
    """
    Reduces the quality of a PNG file.
    first attempt with Image.save(), then use Image.resize()
    """
    file_size = os.path.getsize(file_path)

    if file_size < max_size:
        return
    name = os.path.basename(file_path)
    try:
        with Image.open(file_path) as img:
            #convert to P mode which is more efficient for PNGs
            img = img.convert('P', palette=Image.ADAPTIVE)
            #TODO: does quality_level do anything?
            img.save(output_path, format='PNG')

        file_size = os.path.getsize(output_path)
        mb = file_size / (1024 ** 2)
        print(f"resized {name} to {mb:.2f}")
        if file_size > max_size:
            img = Image.open(output_path)

            while file_size > max_size:
                new_width = int(img.size[0] * scale_factor)
                new_height = int(img.size[1] * scale_factor)

                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                #resave
                img.save(output_path, format='PNG', optimize=True)

                file_size = os.path.getsize(output_path)
                print(f"Resized {name}: {file_size / 1024**2:.2f} MB")

                #break if the image becomes too small
                if img.size[0] < 200 or img.size[1] < 200:
                    break
    except Exception as e:
        print('reduce PNG quality failure')
        print(e)


#TODO: make a faster version
def reduce_jpeg_size(input_path, output_path, target_size=_3_MB, initial_quality=85, step=5):
    with Image.open(input_path) as img:
        # Get the initial image size
        img.save(output_path, 'JPEG', quality=initial_quality)
        target_size_mb = target_size / (1024 * 1024)
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        
        # Reduce quality in steps until the size is below the target size
        quality = initial_quality
        while size_mb > target_size_mb and quality > step:
            quality -= step
            img.save(output_path, 'JPEG', quality=quality)
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"Current size: {size_mb:.2f}MB at quality {quality}")
        
        # If quality is too low, start resizing
        if size_mb > target_size_mb:
            width, height = img.size
            while size_mb > target_size_mb and width > 100 and height > 100:
                width = int(width * 0.9)
                height = int(height * 0.9)
                img = img.resize((width, height), Image.ANTIALIAS)
                img.save(output_path, 'JPEG', quality=quality)
                size_mb = os.path.getsize(output_path) / (1024 * 1024)
                print(f"Current size: {size_mb:.2f}MB at resolution {width}x{height} and quality {quality}")
        
        if size_mb > target_size_mb:
            print("Unable to reduce size below target size with acceptable quality and resolution.")
        else:
            print(f"Final size: {size_mb:.2f}MB at quality {quality}")


#TODO: slower method, better quality??
def resize_image(image_path, output_folder, max_size=_5_MB):
    """Resizes a PNG image to be under the specified max size (default 5MB) and saves it to the output folder."""
    try:
        with Image.open(image_path) as img:
            base_name = os.path.basename(image_path)
            output_path = os.path.join(output_folder, base_name)
            
            while True:
                #save image to a temporary location
                temp_path = os.path.join(output_folder, "temp_" + base_name)
                img.save(temp_path, format='PNG')
                
                if os.path.getsize(temp_path) <= max_size:
                    # Once the file size is acceptable, save the image to the output path
                    os.rename(temp_path, output_path)
                    print(f"Resized {base_name} to under 5MB")
                    break
                
                #reduce image dimensions proportionally to shrink size
                new_width = int(img.width * 0.9)
                new_height = int(img.height * 0.9)
                img = img.resize((new_width, new_height), Image.LANCZOS)
                
                #if the image dimensions get too small and still not under 5MB, stop to avoid excessive quality loss
                if new_width < 100 or new_height < 100:
                    print(f"Cannot resize {base_name} to under 5MB without significant quality loss")
                    break
                
    except Exception as e:
        print(f"Failed to resize {image_path}: {e}")


#TODO: not currently used
def reduce_png_directory(image_dir, max_size=_5_MB, fast=True):
    ld = [i for i in os.listdir(image_dir) if os.path.isfile(os.path.join(image_dir, i))]
    img_paths = [os.path.join(image_dir, img) for img in ld if img.lower().endswith((".png", ".jpg"))]

    if fast:
        with ThreadPoolExecutor() as executor:
            executor.map(reduce_png_quality, img_paths, img_paths * len(img_paths))
    else:
        with ThreadPoolExecutor() as executor:
            executor.map(resize_image, img_paths, [image_dir] * len(img_paths))


# ****** TOKEN REDUCING UTILS ******

def remove_description_pretense(description):
    """
    outliers:
    The image is a photograph taken from a camera, possibly with an iPhone considering the initial context provided.
    The image depicts a close-up photo of
    The image is a portrait-oriented photo taken from a camera, showing a
    The image is taken from a camera and shows a
    """
    #TODO: ss prefix is no longer a part of prompting
    ss_prefix = ''
    if description.startswith("This is NOT a screenshot.\n\n"):
        ss_prefix = "This is NOT a screenshot.\n\n"
        description = description.split(ss_prefix)[1]
    elif description.startswith("This is a screenshot.\n\n"):
        ss_prefix = 'This is a screenshot.\n\n'
        description = description.split(ss_prefix)[1]

    if len(description) < 5:
        return description
    
    if 'from a camera' in description.lower():
        from_camera_split = description.split('from a camera')
        if len(from_camera_split) == 2:
            split1, split2 = from_camera_split
            if len(split1) < 100: #TODO: not great
                description = split2
                if description.startswith('. ') or description.startswith(', '):
                    description = description[2:]
                if description.startswith(' and shows '):
                    description = description.replace(" and shows", "", 1).lstrip()
                elif description.startswith(' showing '):
                    description = description.replace(" showing", "", 1).lstrip()
                return ss_prefix + description

    words = description.split()
    if words[1] == 'image' or words[1] == 'photo':
        third_words = ['shows', 'depicts', 'is', 'displays', 'features', 'captures', 'presents']
        if words[2] in third_words:
            words = words[3:]
            if words[0] == 'of':
                words = words[1:]
        elif words[2] == 'appears':
            words = words[5:]
        elif words[2] == 'provided' and words[3] == 'appears':
            words = words[6:]
    elif 'image' in words[2]:
        words = words[3:]
    elif words[3] == 'image' and words[4] == 'of':
        words = words[5:]
    elif words[3] == 'photo' and words[4] == 'of':
        words = words[5:]

    if words[0][0].isalpha():
        words[0] = words[0][0].upper() + words[0][1:]

    #TODO: inefficient to split whole description into list --> only need first
    new_description = ss_prefix + ' '.join(words)
    return new_description


def remove_description_pretenses_in_file(descr_file, output_file):
    descriptions_json = retrieve_contents_from_json(descr_file)
    for i, d in enumerate(descriptions_json):
        new_descr = remove_description_pretense(d['description'])
        descriptions_json[i]['description'] = new_descr

    with open(output_file, 'w') as file:
        json.dump(descriptions_json, file, indent=2)


# ****** EMBEDDINGS UTILS ******

def add_new_descr_to_embedding_pickle(embeddings_obj, pickle_file, descriptions, create_new=False):
    #one or multiple descr
    #NOTE: np array additions must have same amount of columns(1536)
    if not create_new:
        with open(pickle_file, 'rb') as file:
            existing_embeddings = pickle.load(file)
    else:
        existing_embeddings = []

    if type(descriptions) == str:
        descriptions = [descriptions]

    new_rows = []
    for descr in descriptions:
        new_row = create_single_embedding(embeddings_obj, descr)
        new_rows.append(new_row)

    new_rows = np.array(new_rows).astype('float32')
    if create_new:
        new_embeddings = new_rows
    else:
        new_embeddings = np.vstack((existing_embeddings, new_rows))

    with open(pickle_file, 'wb') as file:
        pickle.dump(new_embeddings, file)


def create_single_embedding(embeddings_obj, description):
    return embeddings_obj.embed_query(description)


def create_and_store_embeddings_to_pickle(embeddings_obj, pickle_file, descriptions):
    """
    embeddings list(np.array(np.array)) - list of descriptions that are converted to embeddings np.arrays
    """
    embeddings_list = []
    for descr in descriptions:
        embeddings_list.append(embeddings_obj.embed_query(descr))

    embeddings_list = np.array(embeddings_list).astype('float32')

    with open(pickle_file, 'wb') as file:
        pickle.dump(embeddings_list, file)


def get_embeddings_from_pickle_file(pickle_file):
    with open(pickle_file, 'rb') as file:
        embeddings_list = pickle.load(file)
    return embeddings_list


def rank_and_filter_descriptions(api_key, descriptions_dict, prompt, filter=1.0):
    """
    helper function for retrieve_and_return. get descriptions dictionary from descriptions json file.
    """
    if filter > 1.0 or filter <= 0.0:
        filter = 1.0
    if len(descriptions_dict) * filter < 1:
        filter = 1.0

    pickle_file = os.path.join(DATA_DIRECTORY, api_key[-5:], "embeddings.pkl")
    print(pickle_file)

    if not os.path.exists(pickle_file):
        assert False, "rank_and_filter_descriptions: no pickle file "
    
    #embeddings search -> return top percentage of ranked descriptions based on filter value
    filtered_images = query_and_filter(api_key, pickle_file, descriptions_dict, prompt, filter)[0]

    filtered_descr_dict = dict()
    for img in list(filtered_images):
        filtered_descr_dict[img] = descriptions_dict[img]
    
    return filtered_descr_dict
    #TODO: still need to return iin ranked form -> cant use dictionary


#TODO: currently not used
def get_top_query_result(api_key, descriptions_file, prompt, filter=1.0):
    """
    helper function for retrieve_and_return. get descriptions dictionary from descriptions json file.
    """
    descriptions_dict = retrieve_contents_from_json(descriptions_file)
    if filter > 1.0 or filter <= 0.0:
        filter = 1
    pickle_file = os.path.join(DATA_DIRECTORY, api_key[-5:], "embeddings.pkl")
    if not os.path.exists(pickle_file):
        assert False, "get_top_query_result: no pickle file "
    
    #embeddings search -> return top percentage of ranked descriptions based on filter value
    filtered_images = query_and_filter(api_key, pickle_file, descriptions_dict, prompt, filter)[0]
    return [filtered_images[0]]


def query_and_filter(api_key, embeddings_pickle_file, descriptions_dict, query, filter):
    file_names = list(descriptions_dict.keys())
    descriptions = list(descriptions_dict.values())
    embeddings_obj = OpenAIEmbeddings(api_key=api_key)

    k = int(len(descriptions) * filter)

    embeddings_list = get_embeddings_from_pickle_file(embeddings_pickle_file)

    index = faiss.IndexFlatL2(1536)
    index.add(embeddings_list)

    query_embedding = embeddings_obj.embed_query(query)
    query_embedding = np.array([query_embedding]).astype('float32')

    distances, indices = index.search(query_embedding, k)

    images_ranked = np.array(file_names)[indices]

    #search_ouput = np.array(descriptions)[indices]
    #print(search_ouput)
    #print(images_ranked)

    return images_ranked


def query_for_related_descriptions(api_key, query, embeddings_pickle_file, images_dir, k=10):
    json_descr_filepath = get_descr_filepath(images_dir)
    json_dict = retrieve_contents_from_json(json_descr_filepath)
    
    file_names = list(json_dict.keys())
    descriptions = list(json_dict.values())

    embeddings_obj = OpenAIEmbeddings(api_key=api_key)

    if not os.path.exists(embeddings_pickle_file):
        add_new_descr_to_embedding_pickle(embeddings_obj, embeddings_pickle_file, descriptions, create_new=True)

    if k == 0:
        k = len(file_names)

    embeddings_list = get_embeddings_from_pickle_file(embeddings_pickle_file)

    index = faiss.IndexFlatL2(1536)
    index.add(embeddings_list)

    query_embedding = embeddings_obj.embed_query(query)
    query_embedding = np.array([query_embedding]).astype('float32')

    distances, indices = index.search(query_embedding, k)

    images_ranked = np.array(file_names)[indices]

    #search_ouput = np.array(descriptions)[indices] NOTE: for looking at ranking results
    #print(search_ouput)
    #print(images_ranked)

    return images_ranked


# ****** LOGGING UTILS ******

def create_logging_entry(input, rephrased_input, output, raw_output):
    current_date_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_obj = {
        'time_stamp' : current_date_time,
        'input' : input,
        'rephrased_input' : rephrased_input,
        'output' : output,
        'raw_output' : raw_output
    }
    return log_obj


#TODO: not currrently used
def create_generate_log_entry(filename, filesize, generate_time):
    current_date_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_obj = {
        'generate_time_stamp' : current_date_time,
        'file_name' : filename, 
        'file_size' : filesize,
        'generate_time' : generate_time
    }
    return log_obj


def store_logging_entry(logging_file, entry):
    """
    save a new single entry to a json logging file
    """
    if not os.path.exists(os.path.dirname(logging_file)):
        os.mkdir(os.path.dirname(logging_file))

    try:
        with open(logging_file, 'r') as file:
            if os.path.getsize(logging_file) != 0:
              existing_data = json.load(file)
            else:
                existing_data = []
    except FileNotFoundError:
        existing_data = []
        print('logging store: error getting existing')

    existing_data.append(entry)

    #write the combined data back to the file
    with open(logging_file, 'w') as file:
        json.dump(existing_data, file, indent=2)
