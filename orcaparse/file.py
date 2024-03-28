import os
import re
import warnings
from typing import Optional

import pandas as pd
from typing_extensions import Iterable, Self

from .data import Data
from .elements import Element, BlockUnknown
from .regex_settings import DEFAULT_ORCA_REGEX_SETTINGS, DEFAULT_GPAW_REGEX_SETTINGS, RegexSettings


class File:

    def __init__(self, file_path: str, regex_settings: Optional[RegexSettings] = None, mode: str = 'ORCA') -> None:
        """
        Initializes the OrcaFile instance.

        Args:
            file_path (str): Path to the file to be processed.
            regex_settings (Optional[RegexSettings]): Custom regex settings for pattern processing. Defaults to None.
            mode (str): Mode of the file. Defaults to 'ORCA', can be 'ORCA' or 'GPAW'.

        Attributes:
            file_path (str): Path to the input file.
            regex_settings (RegexSettings): Regex settings used for pattern processing.
            initialized (bool): Flag indicating whether the instance has been initialized.
            original_text (str): The original text read from the file.
            _blocks (pd.DataFrame): DataFrame containing processed elements.
            _marked_text (list[tuple[tuple[int, int], tuple[int, int], str|Element]]): List of marked text segments. First tuple - char_position, second - line_position, third - text | Element.
            mode (str): Mode of the file, e.g., 'ORCA' or 'GPAW'.
        """
        self.mode: str = mode
        self.file_path: str = file_path
        if regex_settings is None:
            if mode == 'ORCA':
                self.regex_settings = DEFAULT_ORCA_REGEX_SETTINGS
            elif mode == 'GPAW':
                self.regex_settings = DEFAULT_GPAW_REGEX_SETTINGS
            else:
                raise ValueError(
                    f"Invalid mode '{mode}'. Must be 'ORCA' or 'GPAW'.")
        else:
            self.regex_settings: RegexSettings = regex_settings

        self.initialized: bool = False

        # Reading the content of the file.
        with open(self.file_path, "r") as file:
            self.original_text: str = file.read()

        # Initializing the DataFrame to store OrcaElements.
        self._blocks: pd.DataFrame = pd.DataFrame(
            columns=['Type', 'Subtype', 'Element', 'CharPosition' 'LinePosition'])
        self._marked_text: list[tuple[tuple[int, int], tuple[int, int], str | Element]] = [
            ((0, len(self.original_text)),
             (1, self.original_text.count('\n') + 1), self.original_text)
        ]

    def get_structure(self) -> dict[Self, tuple | None]:
        '''
            Structure in a form of nested dict
        '''
        blocks = self.get_blocks()
        return [self, list(blocks['Element'].apply(lambda x: x.get_structure()))]

    def depth(self) -> int:
        return Element.max_depth(self.get_structure())

    def get_blocks(self, show_progress: bool = False) -> pd.DataFrame:
        """
        Returns the DataFrame containing all processed blocks.

        Ensures initialization has occurred before returning the blocks.

        Returns:
            pd.DataFrame: DataFrame containing the processed blocks.
        """
        self.initialize(show_progress=show_progress)
        return self._blocks

    def get_marked_text(self, show_progress: bool = False) -> list[tuple[tuple[int, int], tuple[int, int], Element]]:
        """
        Returns the text with markers after processing patterns.

        Ensures initialization has occurred before returning the marked text.

        Returns:
            str: The marked text.
        """
        self.initialize(show_progress=show_progress)
        return self._marked_text

    def initialize(self, show_progress: bool = False) -> None:
        """
        Initializes the instance by processing patterns if not already done.

        This method sets `self.initialized` to True after processing to avoid redundant initializations.
        """
        if not self.initialized:
            self.process_patterns(show_progress=show_progress)
            self.initialized = True

    def process_patterns(self, show_progress=False):
        """
        Processes the regex patterns defined in the OrcaFile's regex settings to identify, extract, and
        instantiate OrcaElements from the file's text. It updates the internal _blocks DataFrame with the
        extracted elements and their metadata, and replaces identified patterns in the text with unique markers.

        This method performs several steps:
        1. Resets the _blocks DataFrame to ensure it's ready for new data.
        2. Iterates over each regex pattern defined in the file's regex settings.
        3. Uses each pattern to search through the original text, identifying matches.
        4. For each match, extracts relevant data and uses it to instantiate the corresponding OrcaElement subclass.
        5. Generates a unique ID for each extracted element and uses it to replace the original text with a marker.
        6. Updates the _blocks DataFrame with new rows containing the element data, type, subtype, and its position within the text.
        7. Replaces identified patterns in the text with markers that include the type, subtype, and unique ID of the extracted elements.

        Upon completion, the text is fully processed, with all elements identified.
        """
        self._blocks = pd.DataFrame(
            columns=['Type', 'Subtype', 'Element', 'CharPosition', 'LinePosition'])
        self._marked_text: list[tuple[tuple[int, int], tuple[int, int], str | Element]] = [
            ((0, len(self.original_text)),
             (1, self.original_text.count('\n') + 1), self.original_text)
        ]

        self.initialized = True

        for regex in self.regex_settings.to_list():
            self._marked_text, new_blocks = regex.apply(
                self._marked_text, mode=self.mode, show_progress=show_progress)
            new_blocks_df = pd.DataFrame.from_dict(new_blocks, orient="index")
            new_blocks_df['Type'] = regex.p_type
            new_blocks_df['Subtype'] = regex.p_subtype
            self._blocks = pd.concat([self._blocks, new_blocks_df])

        unknown_blocks = {}

        for i, (char_position, line_position, block) in enumerate(self._marked_text):
            if isinstance(block, str):
                unknown_block = BlockUnknown(
                    block, char_position=char_position, line_position=line_position)
                self._marked_text[i] = (
                    char_position, line_position, unknown_block)
                unknown_blocks[hash(unknown_block)] = {
                    'Element': unknown_block, 'CharPosition': char_position, 'LinePosition': line_position}

        unknown_blocks_df = pd.DataFrame.from_dict(
            unknown_blocks, orient="index")
        unknown_blocks_df['Type'] = 'Block'
        unknown_blocks_df['Subtype'] = 'BlockUnknown'

        self._blocks = pd.concat([self._blocks, unknown_blocks_df])

    @staticmethod
    def extract_raw_data_errors_to_none(orca_element: Element) -> str | None:
        """
        Attempts to extract data from an OrcaElement, handling any errors by returning None.

        This nested function is designed to be applied to each row of the DataFrame, specifically to each
        OrcaElement in the 'Element' column. It encapsulates the error-handling logic, ensuring that any
        exceptions raised during data extraction are caught and processed appropriately.

        Parameters:
            orca_element (OrcaElement): An instance of OrcaElement from which data is to be extracted.

        Returns:
            The extracted data from the OrcaElement, or None if an error occurred during the extraction process.
        """
        try:
            # return Data(orca_element.data())
            return orca_element.raw_data
        except Exception as e:
            warnings.warn(
                f"An unexpected error occurred while extracting raw_data from {orca_element}: {e}, returning None instead of data.\n That is really weird")
            return None

    @staticmethod
    def extract_data_errors_to_none(orca_element: Element) -> Data | None:
        """
        Attempts to extract data from an OrcaElement, handling any errors by returning None.

        This nested function is designed to be applied to each row of the DataFrame, specifically to each
        OrcaElement in the 'Element' column. It encapsulates the error-handling logic, ensuring that any
        exceptions raised during data extraction are caught and processed appropriately.

        Parameters:
            orca_element (OrcaElement): An instance of OrcaElement from which data is to be extracted.

        Returns:
            The extracted data from the OrcaElement in orcaparse.Data format, or None if an error occurred during the extraction process.
        """
        try:
            # return Data(orca_element.data())
            return orca_element.data()
        except Exception as e:
            warnings.warn(
                f"An unexpected error occurred while extracting data from {orca_element}: {e}, returning None instead of data.\n Raw context of the element is {orca_element.raw_data}")
            return None

    def search_elements(self, element_type: type[Element] | None = None, readable_name: str | None = None, raw_data_substring: str | Iterable[str] | None = None, raw_data_not_substring: str | Iterable[str] | None = None, show_progress: bool = False) -> pd.DataFrame:
        """
        Searches for OrcaElement instances based on various criteria.

        Parameters:
            element_type (type[Element], optional): The class type of the OrcaElement to search for.
            readable_name (str, optional): The exact term to search for in the readable_name attribute.
            raw_data_substring (str, Iterable[str], optional): The substring to search for within the raw_data attribute.
            raw_data_not_substring (str, Iterable[str], optional): The substring to search the absence of within the raw_data attribute.

        Returns:
            pd.DataFrame: A DataFrame containing the filtered OrcaElements based on the provided criteria.
        """
        self.initialize(show_progress=show_progress)
        blocks_copy = self._blocks.copy()
        blocks_copy['ReadableName'] = blocks_copy['Element'].apply(
            lambda x: x.readable_name())
        blocks_copy['RawData'] = blocks_copy['Element'].apply(
            lambda x: self.extract_raw_data_errors_to_none(x))

        if element_type is not None and len(blocks_copy) > 0:
            blocks_copy = blocks_copy[blocks_copy['Element'].apply(
                lambda x: isinstance(x, element_type))]

        if readable_name is not None and len(blocks_copy) > 0:

            blocks_copy = blocks_copy[blocks_copy['ReadableName']
                                      == readable_name]

        if raw_data_substring is not None and len(blocks_copy) > 0:
            def contains_all_substrings(x_raw_data, substrings):
                # If substrings is a string, convert it to a list for uniformity
                if isinstance(substrings, str):
                    substrings = [substrings]

                # Check if all elements in substrings are in x_raw_data
                return all(substring in x_raw_data for substring in substrings)

            # Filter rows where all substrings are present in the RawData
            matches = blocks_copy['RawData'].apply(
                lambda x: contains_all_substrings(x, raw_data_substring))
            blocks_copy = blocks_copy[matches]

        if raw_data_not_substring is not None and len(blocks_copy) > 0:
            def contains_no_substrings(x_raw_data, substrings):
                # If substrings is a string, convert it to a list for uniformity
                if isinstance(substrings, str):
                    substrings = [substrings]

                # Check if all elements in substrings are not in x_raw_data
                return all(substring not in x_raw_data for substring in substrings)

            # Filter rows where all substrings are not present in the RawData
            matches = blocks_copy['RawData'].apply(
                lambda x: contains_no_substrings(x, raw_data_not_substring))
            blocks_copy = blocks_copy[matches]

        return blocks_copy

    def get_data(self, extract_only_raw: bool = False, element_type: type[Element] | None = None, readable_name: str | None = None, raw_data_substring: str | Iterable[str] | None = None, raw_data_not_substring: str | Iterable[str] | None = None, show_progress: bool = False) -> pd.DataFrame:
        """
        Retrieves and extracts data or raw data strings from OrcaElement instances based on specified search criteria and extraction type.

        This method first searches for OrcaElement instances based on the provided search criteria, which can include the element's type, readable name, or a substring of its raw data. After filtering the elements, it extracts either raw data strings or processed data from them, depending on the 'extract_raw' flag.

        Parameters:
            extract_ony_raw (bool, optional): Determines if `ExtractedData` will be additionally created. If True, it will not. Raw data is stored in `RawData`. Defaults to False.
            element_type (type[Element] | None, optional): The class type of the OrcaElements to filter by. Only elements that are instances of this type or derived from it will be included. Defaults to None, which skips this filter.
            readable_name (str | None, optional): The exact name to match against the 'readable_name' attribute of OrcaElements. Only elements with a matching readable name are included. Defaults to None, which skips this filter.
            raw_data_substring (str | Iterable[str] | None, optional): A substring to search for within the 'raw_data' attribute of OrcaElements. Only elements whose raw data contains this substring are included. Defaults to None, which skips this filter.
            raw_data_not_substring (str | Iterable[str] | None, optional): A substring to search for within the 'raw_data' attribute of OrcaElements. The elements whose raw data contains this substring are not included. Defaults to None, which skips this filter.
            show_progress (bool, optional): Determines if a progress bar is displayed when extracting data from elements. Defaults to False.

        Returns:
            pd.DataFrame: A DataFrame containing the extracted data or raw data strings from the filtered OrcaElements. The DataFrame includes an 'ExtractedData' column with the extracted information. If no elements match the search criteria, an empty DataFrame is returned.
        """
        blocks = self.search_elements(element_type=element_type,
                                      readable_name=readable_name,
                                      raw_data_substring=raw_data_substring,
                                      raw_data_not_substring=raw_data_not_substring,
                                      show_progress=show_progress)
        if not extract_only_raw:
            # Implement the logic to extract processed data from blocks
            extracted_data = blocks['Element'].apply(
                lambda x: self.extract_data_errors_to_none(x))
            blocks['ExtractedData'] = extracted_data
        return blocks

    def create_html(self, css_content: str | None = None, js_content: str | None = None, insert_css: bool = True, insert_js: bool = True, insert_left_sidebar: bool = True, insert_colorcomment_sidebar: bool = True, show_progress: bool = False) -> str:
        """
        Generates a complete HTML document from the processed text, incorporating optional CSS and JavaScript content.

        This method operates in several key steps:
        1. It first ensures that CSS and JavaScript content are set, either to the provided arguments or to default values.
        2. The method then retrieves the processed text with markers using the `get_marked_text` method.
        3. A nested function `replace_marker_with_html` is defined to handle the replacement of each marker within the text
        with the corresponding HTML content generated from the associated OrcaElement. This function:
        - Extracts the type, subtype, and unique ID from each marker.
        - Retrieves the corresponding OrcaElement from the _blocks DataFrame using the unique ID.
        - Calls the `to_html` method on the OrcaElement to generate its HTML representation.
        4. A regular expression is used to find all markers in the processed text, and the `replace_marker_with_html` function
        is applied to replace each marker with its HTML content.
        5. The full HTML document is assembled using the provided or default CSS and JavaScript, along with the body content
        that now includes the HTML representations of the OrcaElements.

        Parameters:
            css_content (str | None): Optional CSS content to include in the <style> tag of the HTML document. If None,
                                    a default CSS content is used.
            js_content (str | None): Optional JavaScript content to include in a <script> tag at the end of the document.
                                    If None, default JavaScript content is used.

        Returns:
            str: A string containing the complete HTML document.

        Raises:
            Exception: If an OrcaElement referenced by a marker cannot be found in the _blocks DataFrame, an exception is raised.

        Note:
            The HTML document includes a structure with a container div, a sidebar for a table of contents (TOC),
            a comment sidebar for additional annotations, and a content area where the main body content is placed.
            The TOC and comment sidebar are expected to be populated by the provided JavaScript.
        """
        if css_content is None:
            # Get the directory of this file
            directory = os.path.dirname(__file__)
            # Construct the path to default.css
            css_file = os.path.join(directory, 'default.css')
            with open(css_file, "r") as file:
                css_content = file.read()

        if js_content is None:
            # Get the directory of this file
            directory = os.path.dirname(__file__)
            # Construct the path to default.js
            js_file = os.path.join(directory, 'default.js')
            with open(js_file, "r") as file:
                js_content = file.read()

        # Process the text to ensure all elements are captured
        processed_text = self.get_marked_text(show_progress=show_progress)

        body_content = ''.join(element[2].to_html()
                               for element in processed_text)

        # Construct the full HTML Document with CSS and JS if requested
        html_content = "<!DOCTYPE html>\n"
        html_content += "<html lang=\"en\">\n<head>\n"
        html_content += "    <meta charset=\"UTF-8\">\n"
        html_content += "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        html_content += "    <title>ORCA</title>\n"

        if insert_css:
            html_content += "    <style>\n        " + \
                (css_content if css_content else "") + "\n    </style>\n"

        html_content += "</head>\n<body>\n"
        html_content += "    <div class=\"container\">\n"

        if insert_left_sidebar:
            html_content += "        <div class=\"sidebar\">\n"
            html_content += "            <!-- Left sidebar content (TOC) -->\n"
            html_content += "            <div class=\"toc\">\n    <!-- JavaScript will populate this area -->\n</div>"
            html_content += "        </div>\n"

        if insert_colorcomment_sidebar:
            html_content += "        <div class=\"comment-sidebar\">\n"
            html_content += "            <!-- comment sidebar for color-comment sections -->\n"
            html_content += "            <!-- JavaScript will populate this area -->\n        </div>\n"

        html_content += "        <div class=\"content\">\n            " + \
            body_content + "\n        </div>\n"
        html_content += "    </div>\n"

        if insert_js:
            html_content += "    <script>\n        " + \
                (js_content if js_content else "") + "\n    </script>\n"

        html_content += "</body>\n</html>"

        return html_content

    def save_as_html(self, output_file_path: str, insert_css: bool = True, insert_js: bool = True, insert_left_sidebar: bool = True, insert_colorcomment_sidebar: bool = True, show_progress=False):
        """
        Generates an HTML document from the OrcaFile instance with customizable options and saves it to the specified file path.

        This method performs the following actions:
        1. Calls the `create_html` method to generate the complete HTML content based on the processed text, optional CSS and JavaScript content, and conditional inclusion of the left sidebar (TOC) and the color-comment sidebar. The `create_html` method assembles the HTML document, incorporating the specified elements and transforms markers within the text into corresponding HTML elements.
        2. Opens the specified output file in write mode. If the file does not exist, it will be created; if it already exists, its content will be overwritten.
        3. Writes the generated HTML content to the file, effectively saving the entire content of the OrcaFile instance as an HTML document at the specified location.

        Parameters:
            output_file_path (str): The file path where the HTML document should be saved. This path includes the file name and extension, for example, 'output/document.html'.
            insert_css (bool, optional): Specifies whether CSS content should be included in the HTML document. Defaults to True.
            insert_js (bool, optional): Specifies whether JavaScript content should be included in the HTML document. Defaults to True.
            insert_left_sidebar (bool, optional): Specifies whether a left sidebar for the Table of Contents (TOC) should be included in the HTML document. Defaults to True.
            insert_colorcomment_sidebar (bool, optional): Specifies whether a comment sidebar for additional annotations should be included in the HTML document. Defaults to True.

        Note:
            This method provides a flexible way to export the content of an OrcaFile instance to a standard HTML format, making it accessible for viewing in web browsers or for further processing with tools that accept HTML input. It allows for the customization of the exported HTML document through parameters that control the inclusion of CSS, JavaScript, and additional structural elements like sidebars.
        """
        html_content = self.create_html(insert_css=insert_css, insert_js=insert_js,
                                        insert_left_sidebar=insert_left_sidebar, insert_colorcomment_sidebar=insert_colorcomment_sidebar, show_progress=show_progress)

        with open(output_file_path, 'w') as output_file:
            output_file.write(html_content)
