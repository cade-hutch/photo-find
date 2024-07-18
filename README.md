# PhotoFind: Semantic Search Tool for Photo Albums

An application thats uses image descriptions as queries to search through a collection of images.  
 Easily find either specific images or a group of related images within personal photo albums, simply describe what you are looking for.

**Description Pre-processing:**  
Using GPT4o's vision capabilities, a description can be generated for each image in an album.

**Text Embeddings**  
The app stores a description, generated from a vision LLM, for each image in a collection. When a user provides a brief description for a specific image or for a group of related images, the app uses text embeddings to rank the relevance of the images descriptions when compared to the user-inputted description. A subset of the highest ranking descriptions are then sent to an LLM that is prompted to find the image(s) that the user is mostly likely to be searching for.

## Demo App

**STEP 1:**  
Go to [photofind.streamlit.app](https://photofind.streamlit.app/)

**STEP 2:**  
Create and submit an OpenAI api key

**STEP 3:**  
Upload selection of images, then click the submission button to kick off descritpion generation.

- The submitted API Key will store your uploads so searches can be done for prior uploads.
- Recommend 20-50 images for a good sample size and an average image size of less than 10MB to keep generation time low.
- Depending on upload speed and image sizes, range for each generation time should be around 10-30 seconds.

**STEP 4:**  
After successful description generation, images can be searched for by entering a search query.

Browse through the images and find one you would like to search for, or use the randomly selected image displayed within the left sidebar as the search subject.

Enter a brief description of the image to search for it. You can be as brief or as descriptive as you like, but keep in mind that more the vague a given description is, the more likely it is that other image(s) in the collection will match the description as well.

Top results for a search will appear at the top of the page. The remaining images will be re-ordered based on their relevance to your given search description. This means that even if a search query does not produce your expected image as a top result, it is likley to still be displayed near the top of the page.
