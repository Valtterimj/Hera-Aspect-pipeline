import os
import numpy as np
from astropy.io import fits
import math
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from aspect_pipeline.levels.level_3.level_3_utilities import nir2_offset_correction, remove_outliers, denoise_spectra

coefficient_folder = os.path.join(os.getcwd(), 'test_data/matlab_coefficients')
vis_coef_path = os.path.join(coefficient_folder, 'vis-conversion.dat')
nir_coef_path = os.path.join(coefficient_folder, 'nir-conversion.dat')
simulated_cube = os.path.join(os.getcwd(), 'test_data/test_outputs/simulated_full_datacube.fits')


# Funtion to get coefficient to convert matlab pixel values into reflectances for specific wavelengths
def get_coef(path:str):
    data = {}
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if line == "" or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 2: 
                try: 
                    wl = float(parts[0])
                    coef = float(parts[1])
                    data[wl] = coef
                except ValueError:
                    print(f'error on line: {line}') 
    return data


# Function to convert to reflectanses

def get_reflectances(spectra, wavelengths):
    vis_coef = get_coef(vis_coef_path)
    nir_coef = get_coef(nir_coef_path)
    all_coef = {**vis_coef, **nir_coef}

    reflectances = np.zeros(len(spectra), dtype=float)
    for i, s in enumerate(spectra):
        v = s / all_coef[wavelengths[i]]
        if i < 10:
            v = v / 0.02
            v += 0.008 # fixed value to reduce some error in the coefficients
        else:
            v = v / 0.04
        reflectances[i] = v
    return reflectances

def readFits(fitsPath, visualise:bool = False):
    name = os.path.splitext(os.path.basename(fitsPath))[0]
    print(f'Reading file: {name}')
    # Open FITS file using astropy
    with fits.open(fitsPath) as hdul:
        print(f'info:\n {hdul.info()}') # Print the info of the hdul
        total_size = hdul._file.size # Total size of the file
        print(f"Total File Size: {total_size} bytes")
        num_extensions = len(hdul) - 1 # Number of extensions
        print(f"Number of Extensions: {num_extensions}")


        # Iterate through each extension
        for i, hdu in enumerate(hdul):
            print('')
            print(f'\nHDU number: {i}') # Extension number
            header = hdu.header
            print(repr(header))
            data = hdu.data
            

            if isinstance(hdu, fits.ImageHDU):
                naxis1 = header.get('NAXIS1')  # Width
                naxis2 = header.get('NAXIS2')  # Height
                naxis3 = header.get('NAXIS3')  # Number of images
                print(f'Data cube shape: {data.shape}')

                print('Image Data:')
                print()

                # for i, image in enumerate(data):
                #     print(f'frame {i}')
                #     plt.imshow(image, cmap='gray')
                #     plt.show()


                # Determine grid layout
                max_images_per_row = 5
                rows = math.ceil(naxis3 / max_images_per_row)
                cols = min(max_images_per_row, naxis3)

                if visualise:
                # Display all 2D images
                    plt.figure(figsize=(cols * 4, rows * 4))
                    plt.suptitle('2D Slices from Data Cube', fontsize=16)
                    for i in range(naxis3):
                        plt.subplot(rows, cols, i + 1)
                        plt.imshow(data[i, :, :], cmap='gray')
                        plt.title(f'Slice {i + 1}')
                        plt.axis('off')

                    plt.tight_layout()
                    plt.show()

# readFits(simulated_cube)

def plot_spectra(spectra, wavelengths):
    plt.figure(figsize=(8, 5))
    plt.plot(wavelengths, spectra, 'b-o', label="Spectrum")
    plt.xlabel("Wavelength (nm)")
    plt.ylabel("Reflectance")
    plt.title("Spectrum vs. Wavelength")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()


def show_mgm_figures(figs):
    for fig in figs:
        canvas = FigureCanvas(fig)
        canvas.draw()  # Renders the figure into the canvas

        # Get actual pixel dimensions
        width, height = canvas.get_width_height()

        # Extract RGBA buffer and reshape it
        buf = np.frombuffer(canvas.buffer_rgba(), dtype=np.uint8).reshape((height, width, 4))

        # Show the image using pyplot
        plt.figure(figsize=fig.get_size_inches())
        plt.imshow(buf)
        plt.axis('off')
        plt.tight_layout()
        plt.show()

def try_and_plot_nir_connection(spectra, wavelengths):
    """
    Testing and visualising nir2 offset correction function. 
    """


    result =  nir2_offset_correction(
		nir1_wavelengths= wavelengths[7:19],
		nir1_spectra= spectra[7:19],
		nir2_wavelengths= wavelengths[19:],
		nir2_spectra= spectra[19:],
		overlap_wavelength = 1225
	)

    nir2_modified, offset = result
    print(f'Nir2 offset: {offset}')
    modified = np.concatenate([spectra[:19], nir2_modified])
    plt.figure(figsize=(10, 5))
    plt.plot(wavelengths, spectra, 'ro-', label="Original Spectra")
    plt.plot(wavelengths, modified, 'bo-', label="nir connected")
    plt.xlabel("Wavelength (nm)")
    plt.ylabel("Reflectance")
    plt.title("Spectra before and after nir1-nir2 connection")
    plt.legend()
    plt.show()
    return modified


def try_and_plot_remove_outliers(spectra, wavelengths):
    corrected_spectra, wavelengths = remove_outliers(spectra, wavelengths)
    plt.figure(figsize=(10, 5))
    plt.plot(wavelengths, spectra, 'ro-', label="Original Spectra")
    plt.plot(wavelengths, corrected_spectra, 'bo-', label="Outliers removed")
    plt.xlabel("Wavelength (nm)")
    plt.ylabel("Reflectance")
    plt.title("Spectra before and after outlier removal")
    plt.legend()
    plt.show()
    return corrected_spectra

def try_and_plot_denoise_spectra(spectra, wavelengths):
    result = denoise_spectra(spectra, wavelengths).flatten()
    plt.figure(figsize=(10, 5))
    plt.plot(wavelengths, spectra, 'ro-', label="Original Spectra")
    plt.plot(wavelengths, result, 'bo-', label="Denoised Spectra")
    plt.xlabel("Wavelength (nm)")
    plt.ylabel("Reflectance")
    plt.title("Spectra before and after denoising")
    plt.legend()
    plt.show()
    return result

def plot_4_spectra(one, two, three, four, wl, names):
    """
    plot four spectras in one plot, one, two, three, four are the different spectras, wl is y-axis and names is a list of labels
    first 4 are the spectra labels corresbondingly and the fifth is the title for the whole plot
    """
    plt.figure(figsize=(10, 5))
    plt.plot(wl, one, 'ko-', label=names[0])
    plt.plot(wl, two, 'ro-', label=names[1])
    plt.plot(wl, three, 'mo-', label=names[2])
    plt.plot(wl, four, 'bo-', label=names[3])
    plt.xlabel("Wavelength (nm)")
    plt.ylabel("Reflectance")
    plt.title(names[4])
    plt.legend()
    plt.show()


def visualise_composition(image, results, coordinates):

    print(f'lenght of composition: {len(results)}')
    print(f'lenght of coordinates: {len(coordinates)}')
    compositions = results[:, :3]

    rgb_image = np.zeros((*image.shape, 3))

    for (row, col), comp in zip(coordinates, compositions):
        rgb_image[row, col] = comp

    rgb_image = np.clip(rgb_image, 0, 1)

    plt.imshow(rgb_image)
    plt.title("OL (R), OPX (G), CPX (B)")
    plt.axis("off")
    plt.show()