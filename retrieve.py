import os
import json
import ast
import time
import re

from openai import OpenAI

from utils import (create_logging_entry, store_logging_entry,
                   retrieve_contents_from_json, rank_and_filter_descriptions)
from fb_db_utils import firebase_store_query_log

MAIN_DIR = os.path.dirname(os.path.realpath(__file__))
DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), 'data')

MODELS = [
    "gpt-3.5-turbo-0125",
    "gpt-4-turbo",
    "gpt-4",
    "gpt-4-1106-preview",
    "gpt-4o"
]


def get_prompt(image_descriptions, option=1):
    """
    get desired retrieval prompt
    """
    if option == 0:
        return (f"You are an assistant for finding image file names based on the associated image descriptions given for each photo."
                f"Here are image filenames as keys and corresponding image descriptions as values in JSON format: {image_descriptions}"
                "The user will ask you for names of one or multiple photos that match a description. You are to output the filename(s) based on the interpreting the respective description given for each photo."
                "For example, if a user asks you for the file names of pictures that have animals in them, find and output all picture file names that contain a reference to an animal in their description."
                "Provide your answer as a list of strings. Simply provide the desired output list, do not include additional explanation. If there are no valid answer, simply output 'None'.")
    if option == 1: #TODO: first line
        return (f"You are an assistant for finding image file names based on the associated image descriptions given for each photo."
                f"Here are image filenames as keys and corresponding image descriptions as values in JSON format: {image_descriptions}"
                "The user will input a brief description that will match one or multiple of the provided full descriptions. You are to output the filename(s) whose descriptions best match the user given description."
                "For example, if a user asks you for the file names of pictures that have animals in them, find and output all picture file names that contain a reference to an animal in their description."
                "Provide your answer as a list of strings. Simply provide the desired output list, do not include additional explanation. If there are no valid answers, simply output 'None'.")


def handle_faulty_response_format(res):
    """
    handle a response from the retrieval prompt if it is not a valid python list of strings
    """
    print(f"FAULTY RESPONSE:\n{res}")

    res_list = []
    if "'''" in res:
        # fix 1
        clean_res = res.replace('json', '', 1).strip()
        res_list = json.loads(clean_res)

    if not res_list and "- " in res: #handle dashed list
        # fix 2
        lines = res.split('\n')
        file_names = []

        for line in lines:
            if line.startswith('-'):
                if '"' in line or "'" in line:
                    file_name = line.strip('- `\'"') 
                    
                file_names.append(file_name)

        return file_names
    
    elif not res_list: #handle plaintext or with []
        if type(res) == str:
            #fix 2.5
            extract_pattern = re.compile(r"(?:^|[\s\"'])([^\"'\s]+)\.png")
            res_list = extract_pattern.findall(res)
            return [s + '.png' for s in res_list]

        print("trying format fix 3")
        #remove the surrounding brackets and strip whitespace
        stripped_string = res.strip('[] \n')
        lines = stripped_string.split('\n')

        parsed_list = []

        for line in lines:
            #strip leading/trailing whitespace, commas, and quotes
            cleaned_line = line.strip(' ,"\n')
            parsed_list.append(cleaned_line)

        return parsed_list
        
    print("handle faulty response attempted")
    return res_list


def retrieve_and_return(image_descriptions_file, retrieval_prompt, api_key, filter=0.1, return_filter=False):
    """
    Send OpenAI api request -- find the image description(s) the user is searching for.

    filter(float): The fraction of top ranking descriptions to send to the model
    return_filter(bool): Return the filtered descriptions that were sent -- Used for testing
    """
    client = OpenAI(api_key=api_key)

    image_descriptions: dict = retrieve_contents_from_json(image_descriptions_file)

    print(api_key)
    print(retrieval_prompt)
    print(image_descriptions)

    if filter is not None:
        image_descriptions = rank_and_filter_descriptions(api_key, image_descriptions,
                                                          retrieval_prompt, filter=filter)
        print(f"filtered descriptions -> only sending {len(image_descriptions)} to api")

    req_start_time = time.perf_counter()
    print('-----')

    retrieval_prompt_orig = retrieval_prompt

    response = client.chat.completions.create(
        model=MODELS[4],
        messages=[
            {"role": "system", "content": get_prompt(image_descriptions, option=1)},
            {"role": "user", "content": f"{retrieval_prompt}"},
        ]
    )
    res_raw = response.choices[0].message.content
    res = res_raw.replace("'", "\"")

    req_stop_time = time.perf_counter()
    
    output_images = []
    try:
        output_images = ast.literal_eval(res)
    except ValueError:
        print("ValueError: The response is not a valid Python literal.")
    except SyntaxError:
        print("SyntaxError: The response string contains a syntax error.")

        formatted_output = handle_faulty_response_format(res)

        print(type(res))
        print(res)
        print("NEW OUT")
        print(formatted_output)

        if type(formatted_output) == list: #TODO: needed?
            output_images = []
            for s in formatted_output:
                if s.endswith((".png", ".jpg")):
                    output_images.append(s)

    print(f"RESPONSE RECEIVED in {round(req_stop_time - req_start_time, 2)}s")

    if type(output_images) == str:
        print('got output as string instead of list')
        output_images = [output_images]

    #store to logs
    logging_entry = create_logging_entry(retrieval_prompt_orig, retrieval_prompt, output_images, str(res_raw))
    firebase_store_query_log(api_key[-5:], logging_entry)

    #localy append to JSON file
    logging_file = os.path.join(DATA_DIRECTORY, api_key[-5:], 'logs.json')
    store_logging_entry(logging_file, logging_entry)

    if return_filter:
        return image_descriptions, output_images
    else:
        return output_images
    