import numbers



"""

This file contains ASPECT calibration conversion functions used. 
E.g. exposure time, wavelenght and detector temperatures. 
The equations and coefficients should be adjusted according to the 
instrument documentation and calibration. 

"""


# TODO: Adjust the coefficients and equations inside each function based on ASPECT instrument documentation and claibration results.


KELVIN: float = 273.15

def exposure_conversion(value: float, channel: str, simulated: bool = False) -> float:
    """
    Converts exposure DN into seconds.

    Parameters:
        value (float): exposure DN
        channel (str): channel
    
    Returns: 
        float exposure in seconds
    """
    # Adjust for simulated data separately
    if simulated:
        match channel:
            case 'Vis':
                return 0.01
            case 'NIR1':
                return 0.02
            case 'NIR2':
                return 0.02
            case _:
                return 'UNK'

    # For real data
    if not isinstance(value, numbers.Number):
        raise ValueError(f"Invalid value for exposure conversion: {value} ({type(value)}); Should be a number.")

    match channel:
        case 'Vis':
            return ((value + 8.6123) / 155.04) / 1000
        case 'NIR1' | 'NIR2':
            return value / 100000
        case 'SWIR':
            return value
        case _:
            raise ValueError(f"Invalid channel for exposure conversion: {channel}; Should be 'Vis', 'NIR1' 'NIR2', or 'SWIR'.")

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
    if value == 0:
        return ('UNK', 'UNK')

    match channel:
        case 'Vis': 
            c = value * 0.6522 - 295.87
        case 'NIR1' | 'NIR2':
            return ('UNK', 'UNK')
        case 'SWIR':
            c = (-6e-11) * value**3 + 3e-6 * value**2 - 0.0188 * value + 17.291
        case _:
            raise ValueError(f"Invalid channel for detector temperature conversion: {channel};  Should be 'Vis', 'NIR1' 'NIR2', or 'SWIR'.")
    k = c + KELVIN
    return (c, k)

def fpi_temp_conversion(value:float, channel: str, fpi: int) -> tuple[float, float]:
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
    match channel:
        case 'Vis':
            return ('N/A', 'N/A')
        case 'NIR1' | 'NIR2' | 'SWIR':
            if fpi == 1:
                c = -0.034 * value + 110.93
            else:
                c = -0.026 * value + 81.01
        case _:
            raise ValueError(f"Invalid channel for fpi temp conversion: {channel};  Should be 'Vis', 'NIR1' 'NIR2', or 'SWIR'.")
        
    k = c + KELVIN
    return (c, k)

def wavelength_conversion(sp: float, channel: str, order: str) -> float:
    """
    Converts the wavelength [nm] from Piezo actuator setpoint value

    Parameters:
        channel: instrument channel
        sp: Piezo actuator setpoint value
        order: the order used in acquisition

    Returns:
        wavelength [nm]
    """

    if not isinstance(sp, numbers.Number):
        raise ValueError(f"Invalid Piezo actuator setpoint value: {sp} ({type(sp)}); Should be a number.")
    
    # TODO: Verify the values
    match (channel, order):
        # The correct values for the corretion needed
        case 'Vis', 'HIGH':
                return round(0.0749 * sp - 786.9)
        case 'Vis', 'LOW':
                return round(0.1244 * sp - 1498.2)
        case 'NIR1', 'HIGH':
                return round(0.1331 * sp - 1823.1)
        case 'NIR1', 'LOW':
                return round(0.2379 * sp - 3190.5)
        case 'NIR2', 'HIGH':
                return round(0.1293 * sp - 1619.4)
        case 'NIR2', 'LOW':
                return round(0.2366 * sp - 2925.8)
        case 'SWIR', _:
                return round(0.2869 * sp - 3847.2)
        case _ , _:
            raise ValueError(f"Invalid channel or order in wavelength conversion: {channel}, {order}.")