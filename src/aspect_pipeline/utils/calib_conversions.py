import numbers


#########################################################################
#
# This file contains ASPECT calibration conversion functions used. 
# E.g. exposure time, wavelenght and detector temperatures. 
# The equations and coefficients should be adjusted according to the 
# instrument documentation and calibration. 
#
#########################################################################

# TODO: Adjust the coefficients and equations inside each function based on ASPECT instrument documentation and claibration results.


kelvin: float = 273.15

def exposure_conversion(value: float, channel: str) -> float:
    """
    Converts exposure DN into seconds.

    Parameters:
        value (float): exposure DN
        channel (str): channel
    
    Returns: 
        float exposure in seconds
    """
    if not isinstance(value, numbers.Number):
        raise ValueError(f"Invalid value for exposure conversion: {value} ({type(value)}); Should be a number.")
    # TODO: add specific coefs for MIRMIS instrument
    if channel == 'NIR':
        return value / 100000
    elif channel == 'MIR':
        return value
    raise ValueError(f"Invalid channel for exposure conversion: {channel}; Should be 'NIR' or 'MIR'.")

def det_temp_conversion(value: float, channel: str) -> tuple[float, float]:
    """
    Converts the 'DET_TEMP' entries from instrument DNs to Celcius and Kelvin.

    Parameters:
        value (float): Detector temperature DN value
        channel (str): Instrument channel

    Returns:
        Tuple[Celsius, Kelvin]
    """
    if not isinstance(value, numbers.Number):
        raise ValueError(f"Invalid value for detector temperature conversion: {value} ({type(value)}); Should be a number.")
    # TODO: add specific values for MIRMIS instrument
    if channel == 'NIR': 
        return ('N/A', 'N/A')
    elif channel == 'MIR':
        if value == 0:
            return ('UNK', 'UNK')
        c = (-6e-11) * value**3 + 3e-6 * value**2 - 0.0188 * value + 17.291
        k = c + kelvin
        return (c, k)
    raise ValueError(f"Invalid channel for detector temperature conversion: {channel}; Should be 'NIR' or 'MIR'.")

def fpi_temp_conversion(value:float, fpi: int) -> tuple[float, float]:
    """
    Converts the FPI temperatures from instrument DNs to Celcius and Kelvin.

    Parameters:
        value (float): Temperature DN value
        channel (str): FPI number

    Returns:
        Tuple(Celsius, Kelvin)
    """
    if not isinstance(value, numbers.Number):
        raise ValueError(f"Invalid value for FPI temperature conversion: {value} ({type(value)}); Should be a number.")
    if fpi not in [1, 2]:
        raise ValueError(f"Invalid FPI value for FPI temperature conversion: {fpi}; Should be 1 or 2.")
    # TODO: add specific coefs for MIRMIS instrument
    if fpi == 1:
        c = -0.034 * value + 110.93
    else:
        c = -0.026 * value + 81.01
    k = c + kelvin
    return (c, k)

def wavelength_conversion(sp: float, channel: str) -> float:
    """
    Converts the wavelength [nm] from Piezo actuator setpoint value

    Parameters:
        channel: instrument channel
        sp: Piezo actuator setpoint value

    Returns:
        wavelength [nm]
    """
    if not isinstance(sp, numbers.Number):
        raise ValueError(f"Invalid Piezo actuator setpoint value: {sp} ({type(sp)}); Should be a number.")
    
    # TODO: add specific coefs for MIRMIS instrument
    if channel == 'NIR':
        wavelength = round(0.1331 * sp - 1823.1, 2)
        return wavelength
    elif channel == 'MIR':
        wavelength = round(0.2869 * sp - 3847.2, 2)
        return wavelength
    raise ValueError(f"Invalid channel in wavelength conversion: {channel}.")