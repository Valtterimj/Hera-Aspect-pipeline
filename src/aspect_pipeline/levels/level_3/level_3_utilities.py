import numpy as np
import cv2
from typing import List, Tuple, Literal, Dict
from numpy.lib.stride_tricks import sliding_window_view
from astropy.io.fits import Header
import inspect
from scipy.ndimage import gaussian_filter1d
from scipy.integrate import trapezoid
from scipy.interpolate import interp1d
from aspect_pipeline.levels.level_3.modules.utilities import return_ddof, find_outliers, normalise_in_columns
from scipy.stats import norm
from aspect_pipeline.levels.level_3.modules._constants import _num_eps
from sklearn.decomposition import PCA
import matplotlib
matplotlib.use('MacOSX')
from matplotlib.patches import Patch
import matplotlib.pyplot as plt
from tqdm import tqdm

def validate_instrument(instrument: str) -> bool:
    """
    Validates if the instrument is one of the 4 options.

    Parameters:
        istrument (str): instrument as a string
    
    Returns:
        True if instrument syntax is correct, else raises a ValueError
    """
    if instrument in ['Vis-NIR1-NIR2', 'Vis-NIR1-NIR2-SWIR', 'NIR1-NIR2', 'NIR1-NIR2-SWIR']:
        return True
    else:
        raise ValueError(f"The defined instrument doesn't match any of expected values: {instrument}")


def normalize_to_8bit(img: np.ndarray) -> np.ndarray:
    # Compute min and max values in the image
    min_val = np.min(img)
    max_val = np.max(img)

    # Avoid division by zero in case all values are the same
    if max_val - min_val == 0:
        return np.zeros_like(img, dtype=np.uint8)

    # Normalize image to range 0-255
    normalized = (img - min_val) / (max_val - min_val) * 255.0

    # Convert to 8-bit integer
    return normalized.astype(np.uint8)

def laplacian(img: np.ndarray) -> np.ndarray:

    # Check if the image was loaded successfully
    if img is None:
        print("Error: Image not found or unable to open")
    
    # Ensure image is float32 and native-endian
    img = img.astype(np.float32, copy=False)
    # # Normalize the image to 8 bit integers
    # img = normalize_to_8bit(img)

    # Apply gaussian blur
    img = cv2.GaussianBlur(img, (5, 5), sigmaX=1.0, sigmaY=1.0)

    # Apply Laplacian operator
    laplacian = cv2.Laplacian(img, cv2.CV_32F, ksize=3)

    return laplacian

def overlay_images(image1, image2, mode='red-green', title='Image Overlay'):
    """
    Overlay two aligned grayscale images using RGB channels to visualize alignment.

    Parameters:
    - image1, image2: 2D NumPy arrays (grayscale images)
    - mode: 'red-green' or 'red-blue' (channel assignment)
    - title: Title for the plot
    """
    # Normalize both images to [0, 1]
    def normalize(img):
        img = img.astype(np.float32)
        return (img - np.min(img)) / (np.max(img) - np.min(img) + 1e-8)

    img1_norm = normalize(image1)
    img2_norm = normalize(image2)

    # Create RGB composite
    rgb = np.zeros((*image1.shape, 3), dtype=np.float32)

    if mode == 'red-green':
        rgb[..., 0] = img1_norm  # Red
        rgb[..., 1] = img2_norm  # Green
    elif mode == 'red-blue':
        rgb[..., 0] = img1_norm  # Red
        rgb[..., 2] = img2_norm  # Blue
    else:
        raise ValueError("Mode must be 'red-green' or 'red-blue'.")

    return(rgb)

def asteroid_mask_two(image: np.ndarray, visualise: bool = True):

    original = image.copy()
    img = np.asarray(image)

    img = img.astype(np.float32, copy=False)
    img_norm = normalize_to_8bit(img)

    blurred = cv2.GaussianBlur(img_norm, (5,5), 0)

    _, th = cv2.threshold(
        blurred, 0, 255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15,17)))
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7,7)))
    th = cv2.morphologyEx(th, cv2.MORPH_ERODE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15,15)))
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7,7)))

    if visualise:

        fig, axs = plt.subplots(1, 2, figsize=(20, 4))
        axs[0].imshow(img_norm, cmap='gray')
        axs[0].set_title("Original (normalised)")
        axs[1].imshow(th, cmap='gray')
        axs[1].set_title("Otsu threshold")
        for ax in axs:
            ax.axis('off')
        plt.tight_layout()
        plt.show()

        legend_elements = [
            Patch(facecolor='yellow', edgecolor='black', label='Aligned regions'),
            Patch(facecolor='red', edgecolor='black', label='Only in original'),
            Patch(facecolor='green', edgecolor='black', label='mask')
        ]

        overlay = overlay_images(original, th)
        plt.figure()
        plt.suptitle('Vis and Nir frame overlay', fontsize=16)
        plt.imshow(overlay)
        plt.axis('off')      
        plt.figlegend(handles=legend_elements, loc='lower center', ncol=3, frameon=True, fontsize='medium')
        plt.tight_layout(rect=[0, 0.05, 1, 0.95])  # Adjust to make room for legend and title
        plt.show()
    return th

def asteroid_mask(image: np.ndarray, erode: int = 2, visualise: bool = False) -> np.ndarray:
    """
    Creates a mask the asteroid. 
    """
    original = image.copy()
    image = image.astype(np.float32, copy=False) # Ensure data is float32
    edges = laplacian(image) # Detect asteroid edges

    # convert to binary mask
    edges_uint8 = cv2.normalize(edges, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _, binary_mask = cv2.threshold(edges_uint8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Apply morphological dilation and closing to fill the asteroid center
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))
    dilated_mask = cv2.morphologyEx(binary_mask, cv2.MORPH_DILATE, kernel, iterations=2)
    closed_mask = cv2.morphologyEx(dilated_mask, cv2.MORPH_CLOSE, kernel, iterations=3)
    
    # Draw the asteroid mask
    contours, _ = cv2.findContours(closed_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    asteroid_mask = np.zeros_like(image, dtype=np.uint8)
    cv2.drawContours(asteroid_mask, contours, -1, 255, thickness=cv2.FILLED)

    # Erode the contours to select only the inner part of the asteroid
    eros_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15,15))
    erosion_mask = cv2.morphologyEx(asteroid_mask, cv2.MORPH_ERODE, eros_kernel, iterations=1 )
    eros_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9,9))
    erosion_mask = cv2.morphologyEx(erosion_mask, cv2.MORPH_ERODE, eros_kernel, iterations=erode )

    if visualise:
        fig, axs = plt.subplots(1, 5, figsize=(20, 4))
        axs[0].imshow(original, cmap='gray')
        axs[0].set_title("Original")
        axs[1].imshow(binary_mask, cmap='gray')
        axs[1].set_title("Edges")
        axs[2].imshow(dilated_mask, cmap='gray')
        axs[2].set_title("Dilated")
        axs[3].imshow(closed_mask, cmap='gray')
        axs[3].set_title("Closing")
        axs[4].imshow(erosion_mask, cmap='gray')
        axs[4].set_title("Final Mask")
        for ax in axs:
            ax.axis('off')
        plt.tight_layout()
        plt.show()
    
        legend_elements = [
            Patch(facecolor='yellow', edgecolor='black', label='Aligned regions'),
            Patch(facecolor='red', edgecolor='black', label='Only in original'),
            Patch(facecolor='green', edgecolor='black', label='mask')
        ]

        overlay = overlay_images(original, erosion_mask)
        plt.figure()
        plt.suptitle('Vis and Nir frame overlay', fontsize=16)
        plt.imshow(overlay)
        plt.axis('off')      
        plt.figlegend(handles=legend_elements, loc='lower center', ncol=3, frameon=True, fontsize='medium')
        plt.tight_layout(rect=[0, 0.05, 1, 0.95])  # Adjust to make room for legend and title
        plt.show()
    
    return erosion_mask

def extract_asteroid(image_cube: np.ndarray, mask_index: int = 0, visualise: bool = False) -> List[Tuple[np.ndarray, np.ndarray]]:
    """
    Extracts the asteroid spectra from the 3D datacube.
    
    Parameters: 
        image_cube (np.ndarray): 3D image cube
        mask_index (int): The frame index used to extract the asteroid coordinates

    Returns:
        List[Tuple[coords, spectra]]: coords are the coordinates of which the spectras are extracted. Coords are a list of 2 e.g. [y, x]
    """
    image = image_cube[mask_index]
    # mask = asteroid_mask(image, erode=2, visualise=visualise)
    mask = asteroid_mask_two(image, visualise=visualise)

    #Store the coordinates of the image where mask has value of non 0
    coords = np.argwhere(mask != 0)
    #Extract the corresponding spectra for coords
    spectra = np.array([image_cube[:, y, x] for y, x in coords])

    #Combine coords and the spectra
    combined = list(zip(coords, spectra))

    return combined

def find_channel_and_local_index(I: int, channel_ids: List, frame_counts: Dict[str, int]):
    cum = 0
    for ch in channel_ids:
        count = frame_counts[f'{ch}']
        if I < cum + count:
            return ch, I - cum
            break
        cum += count
    raise ValueError(f'Index out of range')

def remove_index_from_header(header: Header, index: int) -> Header:

    print(f'removing information about frame index: {index}')
    try: 
        channels = header.get('CHANNELS').split(',')
        total_frames = 0
        frames_per_channel = {}
        for ch in channels:
            task_number = int(header.get(f'{ch}_TASK_NUMBER'))
            total_frames += task_number
            frames_per_channel[f'{ch}'] = task_number
        
        if index > total_frames:
            raise ValueError(f'inndex must be smaller or equal to number of frames {index} <= {total_frames}')

        channel_of_interest, local_index = find_channel_and_local_index(index, channel_ids=channels, frame_counts=frames_per_channel)
        print(f'frame to be removed: channel {channel_of_interest}, index {local_index}')
        num = f'{local_index:03d}'
        val = header[f'AS{channel_of_interest}_TASK_NUMBER']
        header[f'AS{channel_of_interest}_TASK_NUMBER'] = str(int(val)-1)
        frames = header.get(f'AS{channel_of_interest}_FRAMES').split(',')
        frames.remove(num)
        header[f'AS{channel_of_interest}_FRAMES'] = ','.join(frames)
        del header[f'AS{channel_of_interest}_TASK_{num}']
        del header[f'AS{channel_of_interest}_EXP_{num}']
        del header[f'AS{channel_of_interest}_WL_{num}']

        return header
    except Exception as e:
        raise ValueError(f'Removing index {index} from header failed: {e}.')

"""
Connecting segments
"""

def nir2_offset_correction(
		nir1_wavelengths: np.ndarray,
		nir1_spectra: np.ndarray,
		nir2_wavelengths: np.ndarray,
		nir2_spectra: np.ndarray,
		overlap_wavelength: int = 1225,
	):
    """
    Corrects NIR2 spectra by aligning the overlap region with NIR1 spectra using linear regression.

    Parameters:
        nir1_wavelengths (np.ndarray): Wavelengths of NIR1 wavelengths.
        nir1_spectra (np.ndarray): NIR1 spectra.
        nir2_wavelengths (np.ndarray): Wavelengths of NIR2 wavelengths.
        nir2_spectra (np.ndarray): NIR2 spectra.
        overlap_wavelength (int): Wavelength at which to align the spectra.
        test (bool): If True, prints the calculated values.

    Returns:
        corrected_nir2 (np.ndarray): Corrected NIR2 spectra.
        offset (float): Offset value.
    """

    coeffs_nir1 = np.polyfit(nir1_wavelengths[-3:], nir1_spectra[-3:], 1)
    coeffs_nir2 = np.polyfit(nir2_wavelengths[:3], nir2_spectra[:3], 1)

    f_nir1 = np.polyval(coeffs_nir1, overlap_wavelength)
    f_nir2 = np.polyval(coeffs_nir2, overlap_wavelength)


    offset = f_nir1 - f_nir2
    corrected_nir2 = np.clip(nir2_spectra + offset, 0, None)
        
    return corrected_nir2, offset


"""
Find outliers
"""

def accepts_n_params(func, nparams: int):
    if not callable(func):
        return False
    sig = inspect.signature(func)
    return len(sig.parameters) == nparams

def sliding_window(image: np.ndarray, kernel: np.ndarray,
                   func: Literal["conv2", "min", "max", "median", "mean", "std", "sum"] | callable,
                   mode: Literal["full", "same", "valid"] = "same") -> np.ndarray:
    """
    Optimized sliding window function using NumPy's stride tricks.
    !!!!! func must be computed along axis=(2, 3) !!!!!
    e.g. func=lambda im, k: np.var(im, axis=(2, 3))
    """
    if not (accepts_n_params(func, nparams=2) or func in ["conv2", "min", "max", "median",  "mean", "std", "sum"]):
        raise ValueError('"func" must be func(image, kernel) or be in ["conv2", "min", "max", "median",  "mean", "std", "sum"]')
    if mode not in ["full", "same", "valid"]:
        raise ValueError('"mode" must be in ["full", "same", "valid"]')
    kernel = np.array(kernel, dtype=float)
    image = np.array(image, dtype=float)
    kern_h, kern_w = kernel.shape
    if mode == "full":
        pad_h = (kern_h - 1, kern_h - 1)
        pad_w = (kern_w - 1, kern_w - 1)
    elif mode == "same":
        pad_h = (kern_h // 2, (kern_h - 1) // 2)  # Adjust for even-sized kernels
        pad_w = (kern_w // 2, (kern_w - 1) // 2)  # Adjust for even-sized kernels
    else:  # valid
        pad_h = (0, 0)
        pad_w = (0, 0)
    # Pad the image
    image_padded = np.pad(image, (pad_h, pad_w), mode="constant", constant_values=np.nan)
    # Create strided view of the image
    windows = sliding_window_view(image_padded, window_shape=(kern_h, kern_w))
    if callable(func):
        result = func(windows, kernel)
    elif func == "conv2":
        result = np.nansum(windows * np.rot90(kernel, 2), axis=(2, 3))
    elif func == "sum":
        result = np.nansum(windows, axis=(2, 3))
    elif func == "median":
        result = np.nanmedian(windows, axis=(2, 3))
    elif func == "mean":
        result = np.nanmean(windows, axis=(2, 3))
    elif func == "std":
        result = np.nanstd(windows, ddof=return_ddof(kernel), axis=(2, 3))
    elif func == "max":
        result = np.nanmax(windows, axis=(2, 3))
    elif func == "min":
        result = np.nanmin(windows, axis=(2, 3))
    else:
        raise ValueError("Invalid function")
    return result

def interpolate_mask_1d(spectrum: np.ndarray, mask: np.ndarray | None = None,
                        interp_nans: bool = True, fill_value: float = np.nan, keep_edges: bool = True) -> np.ndarray: #fill_value: float = np.nan
    if spectrum.ndim == 2 and spectrum.shape[0] == 1:
        spectrum = spectrum.flatten()
        mask = mask.flatten()
    if mask is None:
        mask = np.zeros_like(spectrum, dtype=bool)
    if interp_nans:
        mask = np.logical_or(mask, ~np.isfinite(spectrum))
    if keep_edges:
        mask[0] = False
        mask[-1] = False
    if np.all(~mask):  # No missing values, return as is
        return spectrum
    
    # Get known (valid) points
    known_x = np.where(~mask)[0]  # Indices of valid points
    known_y = spectrum[~mask]     # Corresponding values

    # Get missing points
    missing_x = np.where(mask)[0]

    # Perform 1D linear interpolation
    interpolator = interp1d(known_x, known_y, kind='linear', bounds_error=False, fill_value=fill_value)
    spectrum[missing_x] = interpolator(missing_x)

    # Replace any remaining NaNs if needed
    if interp_nans:
        spectrum[~np.isfinite(spectrum)] = fill_value
    
    """
    
    This part extrapolates the endpoints if keep_edges is False

    """

    # Handle extrapolation only if keep_edges is False
    if not keep_edges:
        # Manually extrapolate the first point if masked
        if mask[0]:
            # Estimate using first two valid points
            idx1, idx2 = known_x[:2]
            val1, val2 = known_y[:2]
            slope = (val2 - val1) / (idx2 - idx1)
            spectrum[0] = val1 - slope * (idx1 - 0)

        # Manually extrapolate the last point if masked
        if mask[-1]:
            # Estimate using last two valid points
            idx1, idx2 = known_x[-2:]
            val1, val2 = known_y[-2:]
            slope = (val2 - val1) / (idx2 - idx1)
            spectrum[-1] = val2 + slope * (len(spectrum) - 1 - idx2)

    return spectrum.reshape(1, -1)

def remove_outliers(y: np.ndarray, x: np.ndarray | None = None,
                    z_thresh: float = 1, num_eps: float = _num_eps, keep_edges: bool = True) -> np.ndarray | tuple[np.ndarray, ...]:
    inds_to_remove = find_outliers(y=y, x=x, z_thresh=z_thresh, num_eps=num_eps)

    if x is None:
        return np.delete(y, inds_to_remove)
    
    # Create a mask of where outliers are
    mask = np.zeros_like(y, dtype=bool)
    mask[inds_to_remove] = True

    # Interpolate the outliers
    interpolated_y = interpolate_mask_1d(y.copy(), mask=mask, keep_edges=keep_edges)

    # return np.delete(y, inds_to_remove), np.delete(x, inds_to_remove)
    return interpolated_y.flatten(), x


"""
Denoise array
"""

def denoise_array(array: np.ndarray, sigma: float, x: np.ndarray | None = None,
                  z_factor: float = 1, remove_mean: bool = False, sum_or_int: Literal["sum", "int"] = "sum") -> np.ndarray:
    if x is None:
        x = np.arange(0., np.shape(array)[-1])  # 0. to convert it to float

    equidistant_measure = np.var(np.diff(x))

    if equidistant_measure == 0.:  # equidistant step -> gaussian_filter1d is faster
        step = x[1] - x[0]
        fwhm_to_sigma = 1. / np.sqrt(8. * np.log(2.))
        fwhm = 2 * step
        fwhm *= z_factor # Optional tweaking
        sigma = fwhm * fwhm_to_sigma 
        correction = gaussian_filter1d(np.ones(len(x)), sigma=sigma / step, mode="constant")
        array_denoised = gaussian_filter1d(array, sigma=sigma / step, mode="constant")

        array_denoised = normalise_in_columns(array_denoised, norm_vector=correction)

    else:  # transmission application
        # Gaussian filters in columns
        fwhm_to_sigma = 1. / np.sqrt(8. * np.log(2.))
        fwhm = 2 * np.mean(np.diff(x))
        fwhm *= z_factor # Optional tweaking
        sigma = fwhm * fwhm_to_sigma 
        gaussian = norm.pdf(np.reshape(x, (len(x), 1)), loc=x, scale=sigma)

        # need num_filters x num_wavelengths
        if np.ndim(gaussian) == 1:
            gaussian = np.reshape(gaussian, (1, -1))
        if np.ndim(gaussian) > 2:
            raise ValueError("Filter must be 1-D or 2-D array.")

        if sum_or_int == "sum":
            gaussian = normalise_in_columns(gaussian)
            array_denoised = array @ gaussian
        else:
            gaussian = normalise_in_columns(gaussian, trapezoid(y=gaussian, x=x))
            array_denoised = trapezoid(y=np.einsum("...j, kj -> ...kj", array, gaussian), x=x)

    if remove_mean:  # here I assume that the noise has a zero mean
        mn = np.mean(array_denoised - array, axis=-1, keepdims=True)
    else:
        mn = 0.

    return array_denoised - mn

def denoise_spectra(data: np.ndarray, wavelength: np.ndarray, sigma_nm: float | None = 7., z_factor: float = 1) -> np.ndarray:
    if sigma_nm is None:
        return data

    if sigma_nm <= 0.:
        raise ValueError(f'"sigma_nm" must be positive float but equals {sigma_nm}')

    if np.ndim(data) == 1:
        data = np.reshape(data, (1, len(data)))

    return denoise_array(data, sigma=sigma_nm, z_factor=z_factor, x=wavelength)


"""
Analysis results
"""
def get_aspect_default_wl():
    wl_dict = {
        'AS0' : [675., 690., 705., 720., 735., 750., 765., 780., 795., 810., 825.,],
        'AS1' : [875., 904.20738725, 933.40538359, 962.41926832, 991.59052354, 1020.78790557, 1050., 1079.21475545, 1108.41876944, 1137.40366510, 1166.57594038, 1195.77918273, 1225.],
        'AS2' : [1225., 1254.22427930, 1283.43620514, 1312.38308545, 1341.55680112, 1370.76774434, 1400., 1429.23686478, 1458.45946423, 1487.35519223, 1516.53104350, 1545.75237632, 1575.],
        'AS3' : [1675., 1711.363636, 1747.727273, 1784.090909, 1820.454545, 1856.818182 ,1893.181818, 1929.545455, 1965.909091, 2002.272727, 2038.636364, 2075., 2111.363636, 2147.727273, 2184.090909, 2220.454545, 2256.818182, 2293.181818, 2329.545455, 2365.909091, 2402.272727, 2438.636364, 2475.]
    }
    return wl_dict

def get_composition_header() -> Dict[str, Tuple[str, str]]:
    meta_data = {
        'LAYER_00'  :   ('OL (vol%)' , 'Olivine volume percentage'),
        'LAYER_01'  :   ('OPX (vol%)' , 'Orthopyroxene volume percentage'),
        'LAYER_02'  :   ('CPX (vol%)' , 'Clinopyroxene volume percentage'),
        'LAYER_03'  :   ('Fa (OL)' , 'Fayalite component in olivine'),
        'LAYER_04'  :   ('Fo (OL)' , 'Forsterite component in olivine'),
        'LAYER_05'  :   ('Fs (OPX)' , 'Ferrosilite component in orthopyroxene'),
        'LAYER_06'  :   ('En (OPX)' , 'Enstatite component in orthopyroxene'),
        'LAYER_07'  :   ('Fs (CPX)' , 'Ferrosilite component in clinopyroxene'),
        'LAYER_08'  :   ('En (CPX)' , 'Enstatite component in clinopyroxene'),
        'LAYER_09'  :   ('Wo (CPX)' , 'Wollastonite component in clinopyroxene')
    }
    return meta_data

def get_taxonomy_header() -> Dict[str, Tuple[str, str]]:
    meta_data = {
        'LAYER_00'  :   ('A+ = A + Sa' , ''),
        'LAYER_01'  :   ('C+ = C + Cb + Cg + B' , ''),
        'LAYER_02'  :   ('Ch+ = Ch Cgh' , ''),
        'LAYER_03'  :   ('D' , ''),
        'LAYER_04'  :   ('L' , ''),
        'LAYER_05'  :   ('Q' , ''),
        'LAYER_06'  :   ('S+ = S + Sqw + Sr + Srw + Sw' , ''),
        'LAYER_07'  :   ('V+ = V + Vw' , ''),
        'LAYER_08'  :   ('X+ = X + Xc + Xe + Xk' , ''),
        'LAYER_09'  :   ('Other' , ''),
    }
    return meta_data

def spectra_filtering(spectras: np.ndarray, wavelengths: Dict[str, List] | None, instrument: str = 'Vis-NIR1-NIR2'):
    if wavelengths == None: 
        wavelengths = get_aspect_default_wl()
    validate_instrument(instrument=instrument)
    channel_ids = validate_wl(wl=wavelengths, instrument=instrument)
    print(f'Filterin instrument channels {channel_ids}')
    AS0_wl = wavelengths.get('AS0')
    AS1_wl = wavelengths.get('AS1')
    AS2_wl = wavelengths.get('AS2')
    AS3_wl = wavelengths.get('AS3')
    
    selected_wl = []
    for c in channel_ids:
        selected_wl.append(wavelengths.get(f'AS{c}'))
    
    selected_wl = [wl for channel in selected_wl for wl in channel]
    if not len(selected_wl) == len(spectras[0]):
        raise ValueError(f'missmatch between wavelengths and spectra: {len(selected_wl)} != {len(spectras[0])}')

    AS1_start = len(AS0_wl) if 0 in channel_ids else 0 
    AS1_len = len(AS1_wl)
    AS2_len = len(AS2_wl)

    denoised_spectras = []
    for i, spectra in enumerate(tqdm(spectras, desc="Filtering spectra", unit="spec")):
        #3A
        AS1_spectra = spectra[AS1_start : AS1_start + AS1_len]
        AS2_spectra = spectra[AS1_start + AS1_len : AS1_start + AS1_len + AS1_len]
        nir2_offset_correction_result = nir2_offset_correction(
            nir1_wavelengths=AS1_wl,
            nir1_spectra=AS1_spectra,
            nir2_wavelengths=AS2_wl,
            nir2_spectra=AS2_spectra,
            overlap_wavelength=1225.
        )

        connected = np.concatenate(
            [spectra[ : AS1_start + AS1_len], nir2_offset_correction_result[0][1:]] +
            ([spectra[AS1_start + AS1_len + AS2_len :]])
        )
        
        cleaned_wl = np.array(list(dict.fromkeys(selected_wl))) # remove overlap wl
        # # Remove outliers
        cleaned = remove_outliers(connected, cleaned_wl, z_thresh=z_thresh)[0]

        # denoise spectra 
        denoised = denoise_spectra(cleaned, cleaned_wl, z_factor=z_factor).flatten()

        denoised_spectras.append(denoised)

    return(denoised_spectras, cleaned_wl)

"""
Testing utilities
"""


def overlay_images(image1, image2, mode='red-green', title='Image Overlay'):
    """
    Overlay two aligned grayscale images using RGB channels to visualize alignment.

    Parameters:
    - image1, image2: 2D NumPy arrays (grayscale images)
    - mode: 'red-green' or 'red-blue' (channel assignment)
    - title: Title for the plot
    """
    # Normalize both images to [0, 1]
    def normalize(img):
        img = img.astype(np.float32)
        return (img - np.min(img)) / (np.max(img) - np.min(img) + 1e-8)

    img1_norm = normalize(image1)
    img2_norm = normalize(image2)

    # Create RGB composite
    rgb = np.zeros((*image1.shape, 3), dtype=np.float32)

    if mode == 'red-green':
        rgb[..., 0] = img1_norm  # Red
        rgb[..., 1] = img2_norm  # Green
    elif mode == 'red-blue':
        rgb[..., 0] = img1_norm  # Red
        rgb[..., 2] = img2_norm  # Blue
    else:
        raise ValueError("Mode must be 'red-green' or 'red-blue'.")

    return(rgb)
