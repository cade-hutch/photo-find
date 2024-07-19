import base64
import requests
import os
import json
import time
import random

from langchain_community.embeddings import OpenAIEmbeddings

DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), 'data')

from utils import (reduce_png_quality, retrieve_contents_from_json, create_and_store_embeddings_to_pickle,
                   add_new_descr_to_embedding_pickle, remove_description_pretense, reduce_jpeg_size)

IMAGE_QUESTION = 'As descriptive as possible, describe the contents of this image in a single sentence.'


def headers(api_key):
  """
  OpenAI api request header
  """
  return {
  "Content-Type": "application/json",
  "Authorization": f"Bearer {api_key}"
  }


def default_payload(image_question):
  """
  OpenAI api request payload
  """
  return {
    #"model": "gpt-4-turbo",
    "model": "gpt-4o",
    "messages": [
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": f"{image_question}"
          },
          {
            "type": "image_url",
            "image_url": {
              "url": ""
            }
          }
        ]
      }
    ],
    "max_tokens": 400
  }


def encode_image(image_path):
  with open(image_path, "rb") as image_file:
    return base64.b64encode(image_file.read()).decode('utf-8')


def append_to_json_info_file(file_path, data):
    """
    append to info file that stores full requets response objects
    """
    try:
        with open(file_path, 'r') as file:
            if os.path.getsize(file_path) != 0:
              existing_data = json.load(file)
            else:
                existing_data = []
    except FileNotFoundError:
        existing_data = []

    existing_data.append(data)

    info_dir = os.path.dirname(file_path)
    if not os.path.exists(info_dir):
        os.mkdir(info_dir)

    with open(file_path, 'w') as file:
        json.dump(existing_data, file, indent=2)


def append_to_json_file(file_path, data):
    """
    For appending a {image_name : description} pair to the descriptions file 
    """
    try:
        with open(file_path, 'r') as file:
            if os.path.getsize(file_path) != 0:
              existing_data = json.load(file)
            else:
                existing_data = {}
    except FileNotFoundError as e:
        print(f"append_to_json_file: {e}")
        existing_data = {}

    if type(existing_data) == dict:
      existing_data.update(data)
    else:
        #TODO: old json format
        append_to_old_json_file(file_path, existing_data, data)
        assert False, "deprecated JSON description file format"

    with open(file_path, 'w') as file:
        json.dump(existing_data, file, indent=2)


def append_to_old_json_file(file_path, existing_data, data):
    """
    old description storing format
    """
    #depracted JSON format(list of dicts instead if single dict)
    if not list(data.keys()) or list(data.valuess()):
        assert False, "invalid or deprecated JSON description file format"

    new_data = {
        "file_name" : list(data.keys())[0],
        "description" : list(data.valuess())[0]
    }

    # Append the new data to the existing data
    existing_data.append(new_data)

    # Write the combined data back to the file
    with open(file_path, 'w') as file:
        json.dump(existing_data, file, indent=2)


def get_file_names_from_json(json_file_path):
    """
    Get filenames from descriptions file -- should be the keys of a dictionary 
    """
    try:
        with open(json_file_path, 'r') as file:
            data = json.load(file)

            if isinstance(data, dict):
                # if dictionary, search for  keys
                return data.keys()
            elif isinstance(data, list):
                # if list, search for keys in each dictionary
                return [item.get("file_name", None) for item in data]
            else:
                print("Invalid JSON format. Expected a dictionary or a list of dictionaries.")
                return None

    except FileNotFoundError:
        print(f"File not found: {json_file_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        return None


def find_new_pic_files(images_dir, descriptions_file):
    """
    Compare images names found in a directory and image names found in description file,.
    Return image names from the directory that do not have descriptions stored.
    """
    existing_pictures = get_file_names_from_json(descriptions_file)
    if existing_pictures is None:
        existing_pictures = []

    print(f"Descriptions exist for {len(existing_pictures)} images.")
    new_images = []
    for pic in os.listdir(images_dir):
       if pic not in existing_pictures and pic.endswith((".png", ".jpg")) and '.ignore' not in pic:
           new_images.append(pic)
    print(f"Found {len(new_images)} new images.")
    return new_images


def rename_files_in_directory(directory_path):
    """
    Rename all files in the specified directory, remove spaces and shorten to 10 chars max
    #TODO: still needed?
    """
    print('renaming uploaded images')
    if not os.path.isdir(directory_path):
        print("The provided path is not a directory.")
        return

    for filename in os.listdir(directory_path):
        file_path = os.path.join(directory_path, filename)

        if os.path.isfile(file_path):
            new_filename = filename.replace(' ', '_')
            if 'IMG' not in new_filename.upper():
                new_filename = new_filename[-10:]
            new_file_path = os.path.join(directory_path, new_filename)

            os.rename(file_path, new_file_path)
            if file_path != new_file_path:
                print(f"Renamed '{filename}' to '{new_filename}'")


def rename_images(images_dir, img_names):
    """
    Rename all files in the specified directory - remove odd characters.
    Rename with random numbers if needed.
    Take in image folder to make sure no new images match existing ones.
    """
    print("renaming")
    print(img_names)
    if not os.path.isdir(images_dir):
        print("The provided path is not a directory.")
        return

    existing_img_names = [name for name in os.listdir(images_dir)]
    return_img_names = []

    for img_name in img_names:
        extension = img_name.split('.')[-1]
        img_name = img_name.replace(f".{extension}", "")
        img_name = img_name.replace(".", "")
        new_img_name = img_name.replace(' ', '_')
        new_img_name = new_img_name.replace('\u202F', '_')

        if len(new_img_name) > 12:
            new_img_name = new_img_name[-12:]
        while f"{new_img_name}.{extension}" in existing_img_names:
            img_num_list = [str(random.randint(0, 9)) for _ in range(5)]
            img_num = "".join(img_num_list)
            new_img_name = f"IMG{img_num}"

        if not new_img_name.endswith(f".{extension}"):
            new_img_name += f".{extension}"
        print("new image name", new_img_name)
        existing_img_names.append(new_img_name)
        return_img_names.append(new_img_name)

    return return_img_names


def get_pics_without_descrs(images_dir):
    """
    For the given directory of images, find the description file and return list of images
    that are missing a description.
    """
    key_base_dir = os.path.dirname(images_dir)
    json_description_file_path = os.path.join(key_base_dir, 'descriptions.json')

    new_pics = find_new_pic_files(images_dir, json_description_file_path)
    return new_pics


def generate_image_descrptions(new_pics, images_dir, api_key):
    """
    Generator: take in list of images, yield one description per call

    Package an encoded image with the description prompt to get a description for an image.
    Returns tuple(description(str), generation_time(float)) OR 0 for failure
    """
    key_base_dir = os.path.dirname(images_dir)

    json_description_file_path = os.path.join(key_base_dir, 'descriptions.json')
    json_info_file_path = os.path.join(key_base_dir, 'info.json')

    for i, pic in enumerate(new_pics):
        start_time = time.perf_counter()
        print('({}/{}) Getting description for {}'.format(i+1, len(new_pics), pic))

        img_path = os.path.join(images_dir, pic)
        if img_path.endswith(".png"):
            reduce_png_quality(img_path, img_path)
        elif img_path.endswith(".jpg"):
            reduce_jpeg_size(img_path, img_path)

        base64_image = encode_image(img_path)

        start_time_req = time.perf_counter()

        payload = default_payload(IMAGE_QUESTION)
        payload['messages'][0]['content'][1]['image_url']['url'] = f"data:image/jpeg;base64,{base64_image}"

        try_again = False
        attempts = 0
        while attempts < 3:
            attempts += 1
            if attempts > 1:
                print(f"attempt {attempts}")
            try:
                response = requests.post("https://api.openai.com/v1/chat/completions",
                                         headers=headers(api_key),
                                         json=payload)
            except Exception as e: #TODO: specify exceptions
                print(e)
                print('error, sleeping')
                time.sleep(15)
                try_again = True

            if try_again:
                try_again = False
            else:
                break
            
        stop_time_req = time.perf_counter()
        request_time = round(stop_time_req - start_time_req, 2)

        print('response recieved for {} in {} seconds'.format(pic, request_time))

        append_to_json_info_file(json_info_file_path, response.json())

        try:
            response_description = response.json()["choices"][0]["message"]["content"]
            response_description = remove_description_pretense(response_description)

            description_obj = { f"{pic}" : f"{response_description}" }
            append_to_json_file(json_description_file_path, description_obj)

            end_time = time.perf_counter()

            yield (response_description, round(end_time - start_time, 2))

        except KeyError as e:
            print(f"KeyError occurred: {e}")
            print(response.json())
            yield 0

        #TODO: other exceptions?


def update_embeddings(api_key, embeddings_pickle_file, new_descriptions):
    """
    Call utils function to get text embeddings for new descriptions from api request
    and add to embeddings file.
    """
    print('Updating embeddings')
    embeddings_obj = OpenAIEmbeddings(api_key=api_key)
    add_new_descr_to_embedding_pickle(embeddings_obj, embeddings_pickle_file, new_descriptions)
    

def create_embeddings(api_key, embeddings_pickle_file, json_description_file_path):
    """
    Get descriptions for a given api key and call utils ile to create embeddings for them.
    """
    print('Creating embeddings')
    embeddings_obj = OpenAIEmbeddings(api_key=api_key)
    descriptions = retrieve_contents_from_json(json_description_file_path)
    if type(descriptions) == dict:
        descriptions = list(descriptions.values())
    else:
        assert False, "invalid descr retrieve, expecting list of descriptions, {not img:descr} dict"
    create_and_store_embeddings_to_pickle(embeddings_obj, embeddings_pickle_file, descriptions)


if __name__ == '__main__':
    #test creating embeddings
    api_key = ''
    pkl_file = ''
    descr_file = ''

    create_embeddings(api_key, pkl_file, descr_file)