import os
import sys
import time
import io
import requests
import datetime
import firebase_admin

from firebase_admin import credentials, firestore, storage
from PIL import Image


CURR_DIR = os.path.dirname(os.path.realpath(__file__))
DATA_DIRECTORY = os.path.join(CURR_DIR, 'data')

DESCRIPTIONS_FILENAME = 'descriptions.json'

DB_APP_NAME = "image-finder-demo.appspot.com"

keyfile_path = os.path.join(CURR_DIR, 'image-finder-demo-firebase-adminsdk-3kvua-934cc33dbb.json')
if os.path.exists(keyfile_path):
    cred_input = keyfile_path
else:
    cred_input = {
        "type": os.environ.get("FIREBASE_TYPE"),
        "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
        "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
        "private_key": os.environ.get("FIREBASE_PRIVATE_KEY").replace('\\n', '\n'),
        "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
        "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
        "auth_uri": os.environ.get("FIREBASE_AUTH_URI"),
        "token_uri": os.environ.get("FIREBASE_TOKEN_URI"),
        "auth_provider_x509_cert_url": os.environ.get("FIREBASE_AUTH_PROVIDER_X509_CERT_URL"),
        "client_x509_cert_url": os.environ.get("FIREBASE_CLIENT_X509_CERT_URL"),
        "universe_domain": os.environ.get("FIREBASE_UNIVERSE_DOMAIN")
    }

try:
    firebase_admin.get_app()
except ValueError:
    cred = credentials.Certificate(cred_input)
    print('initing app....')
    firebase_admin.initialize_app(cred, {'storageBucket': DB_APP_NAME})
    print('firebase initialized')

db = firestore.client()
bucket = storage.bucket(DB_APP_NAME)


def init_app():
    """
    first function that app.py loop runs to test correct import/db connection
    """
    print('init app dud')


def upload_images_from_list(image_paths, skip_upload=False):
    """
    store images from list of paths to folder in firebase

    images_paths: (list(str))
    """
    if not skip_upload:
        bucket = storage.bucket(DB_APP_NAME)

        folder_name = os.path.basename(os.path.dirname(image_paths[0]))
        folder_name = image_paths[0].split('/')[-3]
        num_imgs = len(image_paths)

        for i, image_pathname in enumerate(image_paths):
            if image_pathname.endswith((".png", ".jpg")):
                image_name = os.path.basename(image_pathname)

                t_start = time.perf_counter()
                blob = bucket.blob(os.path.join('data', folder_name, 'images', image_name))
                t_end1 = time.perf_counter()

                print('finished db connection in {}s'.format(round(t_end1 - t_start, 2)))

                try_again = False
                try:
                    blob.upload_from_filename(image_pathname)
                except Exception as e: #TODO: specify exceptions
                    print(e)
                    print('file upload failed...sleeping and trying again')
                    time.sleep(15)
                    try_again = True
                    print('trying again')
                if try_again:
                    blob.upload_from_filename(image_pathname)

                t_end = time.perf_counter()
                print('({}/{}) finished {} upload in {}s'.format(i+1, num_imgs, image_name, round(t_end - t_start, 2)))


def upload_images_from_dir(folder_path):
    """
    store images in a folder to folder in firebase
    """
    bucket = storage.bucket(DB_APP_NAME)
    folder_name = folder_path.split('/')[-2]

    for filename in os.listdir(folder_path):
        if filename.endswith((".png", ".jpg")):
            t_start = time.perf_counter()
            blob = bucket.blob(os.path.join('data', folder_name, 'images', filename))
            t_end1 = time.perf_counter()

            print('finished db connection in {}s'.format(round(t_end1 - t_start, 2)))

            blob.upload_from_filename(os.path.join(folder_path, filename))

            t_end = time.perf_counter()
            print('finished {} upload in {}s'.format(filename, round(t_end - t_start, 2)))


def fetch_and_process_images(blobs):
    for blob in blobs:
        #the blobcontent is read into memory as bytes
        image_bytes = blob.download_as_bytes()
        
        #bytes convert into a PIL Image object
        image = Image.open(io.BytesIO(image_bytes))
        
        #process the image (e.g., resize, crop, save, etc.)
        print(f"Image format: {image.format}, Image size: {image.size}")


def upload_json_descriptions_file(json_descriptions_file):
    """
    upload JSON file to firebase
    """
    api_key = json_descriptions_file.split('/')[-2]
    bucket = storage.bucket(DB_APP_NAME)

    if json_descriptions_file.endswith((".json")):
        blob = bucket.blob(os.path.join('data', api_key, DESCRIPTIONS_FILENAME))
        blob.upload_from_filename(json_descriptions_file)


def get_file_url(filename):
    bucket = storage.bucket(DB_APP_NAME)
    blob = bucket.blob(filename)
    return blob.generate_signed_url(version="v4",
                                    expiration=datetime.timedelta(minutes=15),
                                    method="GET")


def fetch_image_descriptions(file_url, api_key=None):
    response = requests.get(file_url)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to fetch file: HTTP {response.status_code}")


def list_files_in_folder(folder_name, search_pngs=True):
    bucket = storage.bucket(DB_APP_NAME)
    blobs = bucket.list_blobs(prefix=folder_name)

    if search_pngs and blobs:
        #NOTE: WARNING -- line below prone to cause async issue with streamlit
        return [blob.name for blob in blobs if blob.name.endswith((".png", ".jpg"))]
    elif blobs:
        return [blob.name for blob in blobs]
    else:
        return []


#TODO: refactor this
def does_image_folder_exist(folder_name):
    images_dir = os.path.join("data", folder_name, 'images')

    bucket = storage.bucket(DB_APP_NAME)
    blobs = list(bucket.list_blobs(prefix=images_dir))

    if len(blobs) > 1:
        print('found user image folder in firebase')
        return True
    else:
        print('no user image folder in firebase')
        return False


#TODO: not used --> deprecate
def does_descriptions_file_exist(api_key='', filename=None):
    """
    search for JSON descriptions file in firebase with either an api key or filename
    """
    if filename:
        search = filename
    else:
        search = api_key
    blobs = list_files_in_folder(f'data/{api_key}', search_pngs=False)
    if not blobs:
        return False
    for b in blobs:
        if filename in b.name:
            return True
    return False


def get_remote_image_count(remote_folder, list_imgs=False):
    if not remote_folder.startswith('data/'):
        remote_folder = os.path.join('data', remote_folder)
    if not remote_folder.endswith('images'):
        remote_folder = os.path.join(remote_folder, 'images')

    bucket = storage.bucket(DB_APP_NAME)
    blobs = bucket.list_blobs(prefix=remote_folder)

    if list_imgs:
        names = [blob.name for blob in blobs if blob.name.lower().endswith((".png", ".jpg"))]
        return [n.split('/')[-1] for n in names]
    
    img_count = len([blob.name for blob in blobs if blob.name.lower().endswith((".png", ".jpg"))])
    return img_count


def download_images(remote_folder, local_folder):
    if not remote_folder.startswith('data/'):
        remote_folder = os.path.join('data', remote_folder)
    if not remote_folder.endswith('images'):
        remote_folder = os.path.join(remote_folder, 'images')

    bucket = storage.bucket(DB_APP_NAME)
    blobs = bucket.list_blobs(prefix=remote_folder)

    if not os.path.exists(local_folder):
        os.makedirs(local_folder)

    for blob in blobs:
        if blob.name.lower().endswith((".png", ".jpg")):
            file_path = os.path.join(local_folder, os.path.basename(blob.name))
            if not os.path.exists(file_path):
                blob.download_to_filename(file_path)
                print(f"Downloaded {blob.name} to {file_path}")


def download_descr_file(local_descr_filepath):
    print('******download_descr_file*******')
    print(local_descr_filepath)

    bucket = storage.bucket(DB_APP_NAME)
    filename = os.path.basename(local_descr_filepath)
    basename = os.path.basename(os.path.dirname(local_descr_filepath))

    print('passed in descr filepath', local_descr_filepath)

    db_file_path = os.path.join('data', basename, filename)
    blobs = bucket.list_blobs(prefix=db_file_path)

    for blob in list(blobs):
        print(blob.name)
        if blob.name.endswith(DESCRIPTIONS_FILENAME):
            blob.download_to_filename(local_descr_filepath)
            return


def fetch_images_as_bytes(blobs):
    #TODO: get bytes to skip downloading
    images_bytes = []
    for blob in blobs:
        blob.download_bytes()


#TODO: not used --> deprecate
def compare_dev_local_and_db_imgs(img_folder_name):
    remote_imgs = get_remote_image_count(img_folder_name, list_imgs=True)

    print(remote_imgs)
    local_img_folder = os.path.join(DATA_DIRECTORY, img_folder_name, 'images')
    local_img = [n for n in os.listdir(local_img_folder) if n.endswith((".png", ".jpg"))]

    print(len(remote_imgs))
    print(len(local_img))

    ri_set = set(remote_imgs)
    li_set = set(local_img)

    diff = list(li_set - ri_set)
    print(diff)


if __name__ == "__main__":
    """
    loop in app.py calls via running this script with subprocess.
    This is a workaround for the threading/concurrency issues between streamlit and firebase_admin functions
    """
    descr_file = sys.argv[1]
    image_folder_path = sys.argv[2]
    remote_image_folder_name = image_folder_path.split('/')[-2] #api key abbrev.

    if not os.path.exists(image_folder_path):
        os.makedirs(image_folder_path)

    t_start = time.perf_counter()
    download_descr_file(descr_file)
    download_images(remote_image_folder_name, image_folder_path)
    t_end = time.perf_counter()

    print('finished in {}s'.format(t_end - t_start))
