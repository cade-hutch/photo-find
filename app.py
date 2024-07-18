import os
import time
import random
import streamlit as st
import subprocess
from PIL import Image

from retrieve import retrieve_and_return
from descr_generator import generate_image_descrptions, rename_images, get_new_pics_dir, create_embeddings, update_embeddings
from utils import validate_openai_api_key, get_image_count, get_descr_filepath, query_for_related_descriptions
#TODO: state for importing so firebase only inits once??
from fb_storage_utils import init_app, upload_images_from_list, upload_json_descriptions_file, download_descr_file, does_image_folder_exist

MAIN_DIR = os.path.dirname(os.path.realpath(__file__))
DATA_DIRECTORY = os.path.join(MAIN_DIR, 'data')

JSON_DESCR_FILENAME = 'descriptions.json'

DEPLOYED_PYTHON_PATH = '/home/adminuser/venv/bin/python'

FIXED_WIDTH = 300
FIXED_HEIGHT = 400


def sync_local_with_remote(api_key):
    # TODO: st state to kick off subprocess only once, rest of function
    # TODO     checks completion to be ran on repeat until process complete.
    basename = create_image_dir_name(api_key)
    json_descr_file = os.path.join(DATA_DIRECTORY, basename, JSON_DESCR_FILENAME)
    local_images_folder_path = os.path.join(DATA_DIRECTORY, basename, 'images')

    print('SYNCING LOCAL WITH REMOTE')

    if os.path.exists(DEPLOYED_PYTHON_PATH):
        python_path = DEPLOYED_PYTHON_PATH
    else:
        python_path = 'python'

    proc_cmd = [
        python_path,
        'fb_storage_utils.py',
        json_descr_file,
        local_images_folder_path
    ]
    process = subprocess.Popen(proc_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()

    # Check if the subprocess ended without errors
    if process.returncode == 0:
        return True
    else:
        st.error("Script encountered an error.")
        st.error(stderr.decode())
        return False


def send_request(prompt):
    print(f"SENDING REQUEST: {prompt}")
    print('-----')

    if prompt:
        st.session_state.history = []
        # Append user query to history
        #TODO: make retriee function return that modified phrase, return that to be displayed
        st.session_state.history.append(('text', f"You: {prompt}"))
        
        try:
            images_dir = st.session_state.images_dir
            base_dir = os.path.dirname(images_dir)
            json_file_path = os.path.join(base_dir, JSON_DESCR_FILENAME)
    
            if not os.path.exists(json_file_path):
                print('descriptions file not found, getting from firebase')
                download_descr_file(json_file_path)

            start_t = time.perf_counter()
            output_image_names = retrieve_and_return(json_file_path, prompt, st.session_state.user_openai_api_key)
            end_t = time.perf_counter()

            print('output images list:', output_image_names)
            retrieve_time = format(end_t - start_t, '.2f')

            st.session_state.history.append(('text', f"Found {len(output_image_names)} images in {retrieve_time} seconds"))
        except Exception as e:
            print('error during request')
            print(e)
            output_image_names = []
            st.session_state.history.append(('text', f"No results, try again."))
        
        st.session_state.search_result_images = []
        for img in output_image_names:
            img_path = os.path.join(images_dir, img)
            if os.path.exists(img_path):
                st.session_state.search_result_images.append(img_path)


def create_image_dir_name(api_key):
    return api_key[-5:]


def user_folder_exists_local(api_key):
    folder_name = create_image_dir_name(api_key)

    for f in os.listdir(DATA_DIRECTORY):
        if f == folder_name:
            st.session_state.images_dir = os.path.join(DATA_DIRECTORY, folder_name, 'images')
            print('user_folder_exists_local: True')
            return True
    print('user_folder_exists_local: False')
    return False


def user_folder_exists_remote(api_key):
    folder_name = create_image_dir_name(api_key)
    #TODO: account for db has new pics that local does not
    if does_image_folder_exist(folder_name):
        print('exists_remote: True')
        return True
    else:
        print('exists_remote: False')
        return False


def resize_and_crop_image(image, fixed_width=FIXED_WIDTH, max_height=FIXED_HEIGHT):
    width, height = image.size
    aspect_ratio = height / width

    new_height = int(fixed_width * aspect_ratio)
    
    #resize the image to the fixed width while maintaining aspect ratio
    resized_image = image.resize((fixed_width, new_height))
    
    #crop the image if its height exceeds the max height
    if new_height > max_height:
        top = (new_height - max_height) // 2
        bottom = top + max_height

        resized_image = resized_image.crop((0, top, fixed_width, bottom))
    
    return resized_image


def on_generate_button_submit(uploaded_images, from_uploaded=True, generate=True):
    st.session_state.name_and_image_dict = dict()
    st.session_state.init_display_images = True
    st.session_state.search_result_images = []

    #TODO keep folder as temp?
    foldername = create_image_dir_name(st.session_state.user_openai_api_key)

    images_dir = os.path.join(DATA_DIRECTORY, foldername, 'images')
    st.session_state.images_dir = images_dir

    if not os.path.exists(images_dir):
        os.makedirs(images_dir)
        print('image folder created')
    
    if from_uploaded:
        uploads_to_firestore = []
        uploaded_img_names = [img.name for img in uploaded_images]

        new_uploaded_img_names = rename_images(images_dir, uploaded_img_names)
    
        for uploaded_img, img_name in zip(uploaded_images, new_uploaded_img_names):
            file_path = os.path.join(images_dir, img_name)

            #write the uploaded file to the file system
            with open(file_path, "wb") as f:
                f.write(uploaded_img.getbuffer())
            uploads_to_firestore.append(file_path)

        #TODO: One succuess bar, add images while looping?
        st.success(f"Images saved")
        
        #FIREBASE - STORE IMAGES
        if uploads_to_firestore:
            print('uploading images to firebase')
            upload_images_from_list(uploads_to_firestore)
            print('finished uploading to firebase')

    #NOTE: dev-only param
    if generate:
        if not from_uploaded:
            #TODO: needed for dev
            #rename_files_in_directory(images_dir)
            ...
        new_images = get_new_pics_dir(images_dir)
        new_descriptions = []
        api_key = st.session_state.user_openai_api_key
        generate_total_time = 0.0
        if new_images:
            for i, generation_result in enumerate(generate_image_descrptions(new_images, images_dir, api_key)):
                new_descr = generation_result[0]

                generation_time = generation_result[1]
                generate_total_time += generation_time

                st.write(f"({i+1}/{len(new_images)}) Finished generating for {new_images[i]} in {generation_time} seconds")
                new_descriptions.append(new_descr)

        if type(generate_total_time) == list: #unsuccesful generate/did not finish
            st.error('Error occured while generating... press generate to try again.')
            st.error(generate_total_time[0])
        else:
            generate_total_time = format(generate_total_time, '.2f')
            st.success(f"Finished generating descriptions in {generate_total_time} seconds")

            descr_filepath = get_descr_filepath(images_dir)

            #EMBEDDINGS - LOCAL
            embeddings_pickle_file = os.path.join(DATA_DIRECTORY, foldername, 'embeddings.pkl')
            t_start_embeddings = time.perf_counter()
            if os.path.exists(embeddings_pickle_file):
                st.write("Updating Embeddings....")
                update_embeddings(api_key, embeddings_pickle_file, new_descriptions)
            else:
                st.write("Generating Embeddings....")
                create_embeddings(api_key, embeddings_pickle_file, descr_filepath)

            t_end_embeddings = time.perf_counter()
            embeddings_time = round(t_end_embeddings - t_start_embeddings, 2)

            st.success(f"Finished generating embeddings in {embeddings_time} seconds")

            #FIREBASE - STORE JSON
            print('starting json upload')
            upload_json_descriptions_file(descr_filepath)
            print('finished json upload')

    return True #TODO: handle good/bad return


def create_images_dict(images_dir):
    names_and_images = {}
    image_paths = [os.path.join(st.session_state.images_dir, img)
                    for img in os.listdir(images_dir) if img.endswith((".png", ".jpg"))]

    for img_path in image_paths:
        opened_img = Image.open(img_path)
        cropped_img = resize_and_crop_image(opened_img)
        names_and_images[img_path] = cropped_img
    
    return names_and_images


def retrieval_page():
    images_dir = st.session_state.images_dir
    if len(st.session_state.name_and_image_dict) == 0:
        st.session_state.name_and_image_dict = create_images_dict(images_dir)
    
    images_count = get_image_count(images_dir)
    api_key = st.session_state.user_openai_api_key

    submit_more_images_button = st.button(label='Submit More Images')
    if submit_more_images_button:
        st.session_state.history = []
        st.session_state.show_retrieval_page = False
        st.session_state.upload_more_images = True
        return

    #side bar
    st.sidebar.title("Random image, try to search for this")
    random_img = random.choice(list(st.session_state.name_and_image_dict.values()))
    st.sidebar.image(random_img, use_column_width=True)

    st.text("Search through {} images submitted by API Key: {}".format(images_count, api_key))

    with st.form('prompt_submission'):
        text_input_col, submit_btn_col = st.columns([5, 1])
        with text_input_col:
            user_input = st.text_input(label="why is this required", label_visibility='collapsed',
                                       key="user_input", placeholder="What would you like to find?")

        with submit_btn_col:
            submit_button = st.form_submit_button(label='Send')

    if submit_button:
        #no longer display images without search results
        st.session_state.init_display_images = False
        
        #TODO: needed?
        top_col1, top_col2 = st.columns(2)
        folder_name = os.path.dirname(images_dir)
        embeddings_pickle_file = os.path.join(DATA_DIRECTORY, folder_name, 'embeddings.pkl')

        print("FILE NAMES:")
        print(embeddings_pickle_file)
        print(images_dir)

        t_start = time.perf_counter()
        images_ranked = query_for_related_descriptions(api_key, user_input, embeddings_pickle_file, images_dir, k=0)

        print('\n------------------------------NEW SEARCH------------------------------')
        
        if len(images_ranked[0]) > 1:
            st.session_state.images_ranked = images_ranked[0].tolist()
            st.session_state.all_images = [os.path.join(st.session_state.images_dir, img)
                                               for img in st.session_state.images_ranked]

        t_end = time.perf_counter()
        print(f"Embeddings Ranking Time: {round(t_end - t_start, 2)}s")
        send_request(user_input)
    
    if st.session_state.init_display_images:
        img_list = list(st.session_state.name_and_image_dict.values())
        for i in range(0, len(img_list), 4):
            col1, col2, col3, col4 = st.columns(4)

            i1 = img_list[i]

            col1.image(i1, use_column_width=True)
            
            if i + 1 < len(img_list):
                i2 = img_list[i+1]
                col2.image(i2, use_column_width=True)
            if i + 2 < len(img_list):
                i3 = img_list[i+2]
                col3.image(i3, use_column_width=True)
            if i + 3 < len(img_list):
                i4 = img_list[i+3]
                col4.image(i4, use_column_width=True)

    images_to_display = []
    for item_type, content in st.session_state.history:
        if item_type == 'text':
            st.text(content)
        elif item_type == 'image':
            images_to_display.append(content)

    for i in range(0, len(st.session_state.search_result_images), 2):
        col1, col2 = st.columns(2)

        res_img = st.session_state.name_and_image_dict[st.session_state.search_result_images[i]]
        col1.image(res_img, use_column_width=True, caption="Top Result")
        
        if i + 1 < len(st.session_state.search_result_images):
            res_img = st.session_state.name_and_image_dict[st.session_state.search_result_images[i+1]]
            col2.image(res_img, use_column_width=True, caption='Top Tesult')

    #display rest of images in ranked order
    if not st.session_state.init_display_images:
        remaining_images = [img for img in st.session_state.all_images 
                                    if img not in st.session_state.search_result_images]
    else:
        remaining_images = []

    for i in range(0, len(remaining_images), 4):
        col1, col2, col3, col4 = st.columns(4)

        i1 = st.session_state.name_and_image_dict[remaining_images[i]]

        col1.image(i1, use_column_width=True)
        
        if i + 1 < len(remaining_images):
            i2 = st.session_state.name_and_image_dict[remaining_images[i+1]]
            col2.image(i2, use_column_width=True)
        if i + 2 < len(remaining_images):
            i3 = st.session_state.name_and_image_dict[remaining_images[i+2]]
            col3.image(i3, use_column_width=True)
        if i + 3 < len(remaining_images):
            i4 = st.session_state.name_and_image_dict[remaining_images[i+3]]
            col4.image(i4, use_column_width=True)


def main():
    st.title('Photo Find')
    footer = """
        <style>
            .footer {
                position: fixed;
                left: 0;
                bottom: 0;
                width: 100%;
                background-color: #111;
                color: white;
                text-align: center;
            }
        </style>
        <div class="footer">
            <p>By Cade Hutcheson</p>
        </div>
     """
    st.markdown(footer, unsafe_allow_html=True)

    #API key submission page
    if not st.session_state.submitted_api_key:
        st.write('Submit an OpenAI API Key to begin')

        with st.form('api_key_submission'):
            api_key_text_input_col, api_key_submit_btn_col = st.columns([5, 1])
            with api_key_text_input_col:
                user_api_key_input = st.text_input(label="why is this required", label_visibility='collapsed',
                                                   key="user_api_key_input", placeholder="Enter OpenAI API key")

            with api_key_submit_btn_col:
                submit_api_key_button = st.form_submit_button(label='Submit')
    
        if submit_api_key_button:
            if validate_openai_api_key(user_api_key_input):
                st.session_state.user_openai_api_key = user_api_key_input
                st.session_state.submitted_api_key = True

                st.success('API key validated')

                #TODO: check for embeddings
                remote_folder_exists = user_folder_exists_remote(user_api_key_input) #firestore folder exists

                if user_folder_exists_local(user_api_key_input):
                    st.session_state.api_key_exists = True
                    # if remote_folder_exists:
                    #     #TODO: compare image counts here****************************
                    #     if sync_local_with_remote(user_api_key_input):
                    #     #TODO: validate with remote?
                elif remote_folder_exists:
                    st.session_state.api_key_exists = True
                    if sync_local_with_remote(user_api_key_input):
                        print('passed syncing')
            else:
                st.error('Error occured while validating API key.... refresh page to try again.')

    #Image upload page
    #TODO: make own function? --> user has to click 'Submit More Images' twice for this to display
    display_upload_page = (st.session_state.submitted_api_key
                           and not st.session_state.has_submitted_images
                           and not st.session_state.api_key_exists)
    if display_upload_page or st.session_state.upload_more_images:
        if st.session_state.upload_more_images:
            st.write(f"Submit more images for {st.session_state.user_openai_api_key}")
        else:
            st.write('Submit images for description generation')

        uploaded_files = st.file_uploader("Choose images...",
                                          type=['png', 'jpeg', 'jpg'],
                                          accept_multiple_files=True)

        if uploaded_files:
            generate_submit_button = st.button(label=f"Click here to generate descriptions for {len(uploaded_files)} images")
            if generate_submit_button:
                if on_generate_button_submit(uploaded_files):
                    st.session_state.upload_more_images = False
                    st.session_state.has_submitted_images = True
                    st.session_state.show_retrieval_page = True
    
    if st.session_state.has_submitted_images or st.session_state.api_key_exists:
        if st.session_state.api_key_exists and st.session_state.display_infobar_for_existing_images:
            #one time info bar: tell user there are existing picture the submitted
            st.info('Found Existing images for submitted API Key.')
            st.session_state.display_infobar_for_existing_images = False

        if st.session_state.api_key_exists and not st.session_state.all_descriptions_generated:
            #if a previous api key is submitted, check if images/descriptions are matching
            if not st.session_state.images_dir:
                key_dir_name = create_image_dir_name(st.session_state.user_openai_api_key)
                st.session_state.images_dir = os.path.join(DATA_DIRECTORY, key_dir_name, 'images')

            pics_missing_descriptions = get_new_pics_dir(st.session_state.images_dir)
            if pics_missing_descriptions:
                print('images without descriptions found')
                
                continue_generating_button = st.button(label=f'Continue generating for {len(pics_missing_descriptions)} images')
                if continue_generating_button:
                    print('display continue generating page')
                    if on_generate_button_submit(pics_missing_descriptions, from_uploaded=False):
                        st.session_state.all_descriptions_generated = True
            else:
                st.session_state.all_descriptions_generated = True
        if st.session_state.show_retrieval_page:
            retrieval_page()


def make_st_vars():
    #app start point
    if 'firebase_init' not in st.session_state:
        print('initing app')
        st.session_state.firebase_init = True
        init_app()

    if 'submitted_api_key' not in st.session_state:
        st.session_state.submitted_api_key = False

    if 'api_key_exists' not in st.session_state:
        st.session_state.api_key_exists = False

    if 'has_submitted_images' not in st.session_state:
        st.session_state.has_submitted_images = False

    if 'upload_more_images' not in st.session_state:
        st.session_state.upload_more_images = False

    if 'history' not in st.session_state:
        st.session_state.history = []

    if 'all_images' not in st.session_state:
        st.session_state.all_images = []

    if 'images_dir' not in st.session_state:
        st.session_state.images_dir = ""
    elif os.path.exists(st.session_state.images_dir):
        st.session_state.all_images = []
        for img in os.listdir(st.session_state.images_dir):
            if img.endswith((".png", ".jpg")):
                st.session_state.all_images.append(os.path.join(st.session_state.images_dir, img))

    if 'images_ranked' not in st.session_state:
        st.session_state.images_ranked  = []

    if 'all_descriptions_generated' not in st.session_state:
        st.session_state.all_descriptions_generated = False

    if 'display_infobar_for_existing_images' not in st.session_state:
        st.session_state.display_infobar_for_existing_images = True

    if 'show_retrieval_page' not in st.session_state:
        st.session_state.show_retrieval_page = True

    if 'search_result_images' not in st.session_state:
        st.session_state.search_result_images = []
    
    if 'name_and_image_dict' not in st.session_state:
        st.session_state.name_and_image_dict = dict()

    if 'init_display_images' not in st.session_state:
        st.session_state.init_display_images = True


make_st_vars()
main()

