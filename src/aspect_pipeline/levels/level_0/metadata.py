import logging
import json

from pathlib import Path
from datetime import datetime

from aspect_pipeline.utils.classes import InputLayout, Metadata, AcqMetadata, SpiceMetadata, InstrumentMetadata, InstrumentSpecificMetadata, DataConfig, Issue, HeaderEntry
from aspect_pipeline.utils.utilities import channel_to_id, get_current_utc_time_str, list_channel_frames, extract_frames, check_order
from aspect_pipeline.utils.validate import _validate_float_string
from aspect_pipeline.utils.errors import PipelineError
import aspect_pipeline.levels.level_0.spice as spice

logger = logging.getLogger(__name__)

def collect_metadata(input: InputLayout, spice: Path, cfg: DataConfig, channel: str) -> tuple[Metadata, list[Issue]]:
    """
    Collect all acquisition metadata, including spice data, acquisition, and isntrument related metadata. 
    
    :param input: inputLayout object (contains paths)
    :type input: InputLayout
    :param spice: SPICE meta kernel path
    :type spice: Path
    :param cfg: pipeline configurations object
    :type cfg: DataConfig
    :param channel: Acquisition channel
    :type channel: str
    :return: Metadata object containing all relevant fields and list of issues happened during metadata collection.
    :rtype: tuple[Metadata, list[Issue]]
    """
    all_issues: list[Issue] = []

    tel_path = input.telemetry_json
    acq_dir = input.acquisition_dir
    conf_path = input.config_json
    target = cfg.target
    solar_d = cfg.solar_d

    frame_number, list_of_frames = list_channel_frames(acq_dir=acq_dir, channel=channel)
    if frame_number == 0:
        raise PipelineError(f"No acquisitions", channel=channel, level='0A', stage='collect_metadata', path=acq_dir)
    else: 
        original_filename = list_of_frames[0]

    acq_metadata, acq_issues = collect_config_metadata(telemetry_path=tel_path, data=cfg, orig_file=original_filename)
    all_issues.extend(acq_issues)
    utc_ob = acq_metadata.DATE_OBS # should use SC_CLK for more accurate?
    spice_metadata, spice_issues = collect_spice_metadata(mk=spice, target=target, solar_d=solar_d, utc_ob=utc_ob)
    all_issues.extend(spice_issues)
    instrument_metadata, inst_issues = collect_instrument_metadata(telemetry_path=tel_path, channel=channel)
    all_issues.extend(inst_issues)
    instrument_specific_metadata, inst_spec_issues = collect_instrument_specific_metadata(config_path=conf_path, acq_path=acq_dir, channel=channel)
    all_issues.extend(inst_spec_issues)

    meta_data = Metadata(
                    acq=acq_metadata,
                    spice=spice_metadata,
                    instrument=instrument_metadata,
                    instrument_specific=instrument_specific_metadata

                )
    
    return (meta_data, all_issues)


def collect_spice_metadata(mk: Path, target: str, solar_d: str | None, utc_ob: str) -> tuple[SpiceMetadata, list[Issue]]:

    issues: list[Issue] = []
    meta_data = {}

    solar_d = _validate_float_string(value=solar_d) # either a valid string or None

    mk = str(mk)
    try:
        spice.load_meta_kernel(mk) # Load the meta kernel
    except Exception as e:
        issues.append(
            Issue(
                level="warning",
                message=(f"Failed to load meta kernel {mk}; "
                        f"Continuing with 'UNK defaults (reson: {type(e).__name__})"
                        ),
                source=__name__,

            )
        )
        if solar_d is None:
            solar_d = 'UNK'

        meta_data['SPICE_MK'] = HeaderEntry('UNK', 'SPICE metakernel')
        meta_data['SPICEVER'] = HeaderEntry('UNK', 'SPICE dataset version')
        meta_data['SPICECLK'] = HeaderEntry('UNK', 'SC clock SPICE format')
        meta_data['SUN_POSX'] = HeaderEntry('UNK', 'Sun position vector X [km]')
        meta_data['SUN_POSY'] = HeaderEntry('UNK', 'Sun position vector Y [km]')
        meta_data['SUN_POSZ'] = HeaderEntry('UNK', 'Sun position vector Z [km]')
        meta_data['SOLAR_D']  = HeaderEntry(solar_d, 'Solar distance')
        meta_data['EARTPOSX'] = HeaderEntry('UNK', 'Earth position vector X [km]')
        meta_data['EARTPOSY'] = HeaderEntry('UNK', 'Earth position vector Y [km]')
        meta_data['EARTPOSZ'] = HeaderEntry('UNK', 'Earth position vector Z [km]')
        meta_data['EARTH_D']  = HeaderEntry('UNK', 'Earth distance')
        meta_data['TARGET'] = HeaderEntry(f'{target}', 'Observation target')
        meta_data['TRG_POSX'] = HeaderEntry('UNK', 'Target position vector X [km]')
        meta_data['TRG_POSY'] = HeaderEntry('UNK', 'Target position vector Y [km]')
        meta_data['TRG_POSZ'] = HeaderEntry('UNK', 'Target position vector Z [km]')
        meta_data['TRG_DIST']  = HeaderEntry('UNK', 'Target distance')
        meta_data['SC_QUATW'] = HeaderEntry('UNK', 'Spacecraft quaternion (W)')
        meta_data['SC_QUATX'] = HeaderEntry('UNK', 'Spacecraft quaternion (X)')
        meta_data['SC_QUATY'] = HeaderEntry('UNK', 'Spacecraft quaternion (Y)')
        meta_data['SC_QUATZ'] = HeaderEntry('UNK', 'Spacecraft quaternion (Z)')
        meta_data['CAM_RA'] = HeaderEntry('UNK', 'Camera axis RA [deg]')
        meta_data['CAM_DEC'] = HeaderEntry('UNK', 'Camera axis DEC [deg]')
        meta_data['CAM_NAZ'] = HeaderEntry('UNK', 'Camera axis north azimuth [deg]')
        meta_data['SOL_ELNG'] = HeaderEntry('UNK', 'Solar elongation')

        return (meta_data, issues)

    et = spice.utc_2_et(utc_ob)
    milani_frame = 'MILANI_SPACECRAFT'
    camera_frame = 'MILANI_NAVCAM'

    mk_id = spice.query_mk_identifier() # Meta kernel version
    meta_data['SPICE_MK'] = HeaderEntry(mk_id, 'SPICE metakernel')

    spice_version = spice.query_spice_version() # SPICE dataset version
    meta_data['SPICEVER'] = HeaderEntry(spice_version, 'SPICE dataset version')

    sclk = spice.get_sclk(et, milani_frame) # SC clock in spice format
    meta_data['SPICECLK'] = HeaderEntry(sclk, 'SC clock SPICE format')

    # Sun position vector and distnace from observer
    sun_position, sun_distance_au = spice.query_position_distance(target='SUN', et=et, frame='J2000', abcorr='NONE', observer=milani_frame)

    if solar_d is not None:
        sun_distance_au = solar_d
        if sun_distance_au != 'UNK':
            issues.append(
                Issue(
                    level='warning',
                    message=f"A valid solar distance was found from SPICE kernel but overrided with solar_d configuration parameter.\n SPICE: {sun_distance_au}, used: {solar_d}.",
                    source=__name__,
                )
            )
    meta_data['SUN_POSX'] = HeaderEntry(sun_position[0], 'Sun position vector X [km]')
    meta_data['SUN_POSY'] = HeaderEntry(sun_position[1], 'Sun position vector Y [km]')
    meta_data['SUN_POSZ'] = HeaderEntry(sun_position[2], 'Sun position vector Z [km]')
    meta_data['SOLAR_D']  = HeaderEntry(sun_distance_au, 'Solar distance')

    # Earth position vector and distnace from observer
    earth_position, earth_distance_au = spice.query_position_distance(target='EARTH', et=et, frame='J2000', abcorr='NONE', observer=milani_frame)
    meta_data['EARTPOSX'] = HeaderEntry(earth_position[0], 'Earth position vector X [km]')
    meta_data['EARTPOSY'] = HeaderEntry(earth_position[1], 'Earth position vector Y [km]')
    meta_data['EARTPOSZ'] = HeaderEntry(earth_position[2], 'Earth position vector Z [km]')
    meta_data['EARTH_D']  = HeaderEntry(earth_distance_au, 'Earth distance')

    # Observation target in SPICE format
    meta_data['TARGET'] = HeaderEntry(target, 'Observation target')

    # Target position vector and distnace from observer
    target_position, target_distance_au = spice.query_position_distance(target=target, et=et, frame='J2000', abcorr='NONE', observer=milani_frame)
    meta_data['TRG_POSX'] = HeaderEntry(target_position[0], 'Target position vector X [km]')
    meta_data['TRG_POSY'] = HeaderEntry(target_position[1], 'Target position vector Y [km]')
    meta_data['TRG_POSZ'] = HeaderEntry(target_position[2], 'Target position vector Z [km]')
    meta_data['TRG_DIST']  = HeaderEntry(target_distance_au, 'Target distance')
    
    # Spacecraft quaternions
    quaternions = spice.query_spacecraft_quaternions(frame_name=milani_frame, et=et, tol=1, ref='J2000' ) # Quaternions are returned in format (X, Y, Z, W)
    meta_data['SC_QUATW'] = HeaderEntry(quaternions[3], 'Spacecraft quaternion (W)')
    meta_data['SC_QUATX'] = HeaderEntry(quaternions[0], 'Spacecraft quaternion (X)')
    meta_data['SC_QUATY'] = HeaderEntry(quaternions[1], 'Spacecraft quaternion (Y)')
    meta_data['SC_QUATZ'] = HeaderEntry(quaternions[2], 'Spacecraft quaternion (Z)')

    # Camera attitude
    ra_deg, dec_deg, naz_deg = spice.query_camera_pointing_info(camera_frame=camera_frame, et=et, inertial_frame='J2000', target_frame='DIDYMOS_FIXED')
    meta_data['CAM_RA'] = HeaderEntry(ra_deg, 'Camera axis RA [deg]')
    meta_data['CAM_DEC'] = HeaderEntry(dec_deg, 'Camera axis DEC [deg]')
    meta_data['CAM_NAZ'] = HeaderEntry(naz_deg, 'Camera axis north azimuth [deg]')

    # Camera solar elongation
    solar_angle = spice.query_camera_solar_elongation(camera_frame=camera_frame, et=et, abcorr='NONE',observer=milani_frame)
    meta_data['SOL_ELNG'] = HeaderEntry(solar_angle, 'Solar elongation')

    spice.unload_all_kernels() # Unload all kernels at the end

    spice_meta_data = SpiceMetadata(**meta_data)
    return (spice_meta_data, issues)

def collect_config_metadata(telemetry_path: Path, data: DataConfig, orig_file: str) -> tuple[AcqMetadata, list[Issue]]:

    # TODO: where and how the Spacecraft clock count to SC_CLK is read and saved?


    issues: list[Issue] = []
    meta_data = {}
    try:
        telemetry_data = json.loads(telemetry_path.read_text(encoding='utf-8'))
        acq_date = telemetry_data.get('ACQ_DATE', None)
        dt = datetime.strptime(acq_date, "%a %b %d %H:%M:%S %Y")
        date_obs = dt.strftime("%Y-%m-%dT%H:%M:%S.000")
    except Exception as e:
        issues.append(
            Issue(
                level="warning",
                message=(f"Missing field in telemetry for 'ACQ_DATE';"
                            f"Continuing with 'UNK' default (reson: {type(e).__name__})"
                            ),
                source=__name__,

            )
        )
        date_obs = 'UNK'
    meta_data['INSTRUME'] = HeaderEntry(data.instrume, 'Camera ID')
    meta_data['ORIGIN'] = HeaderEntry(data.origin, 'Mission imagin instrument')
    meta_data['MISSPHAS'] = HeaderEntry(data.missphas, 'Mission phase ID')
    meta_data['OSERV_ID'] = HeaderEntry(data.observ, 'Observation ID')
    meta_data['ORIGFILE'] = HeaderEntry(orig_file, 'Original filename')
    meta_data['SWCREATE'] = HeaderEntry(data.swcreate, 'Software identification')
    meta_data['DATE_OBS'] = HeaderEntry(date_obs, 'Observation time UTC')
    meta_data['OBJECT'] = HeaderEntry(data.object, 'Observation target')
    meta_data['PROCLEVL'] = HeaderEntry('0A', 'Calibration level')
    meta_data['FILENAME'] = HeaderEntry('UNK', 'Filename')
    meta_data['DATE'] = HeaderEntry(get_current_utc_time_str(), 'File creation UTC')
    meta_data['SC_CLK'] = HeaderEntry('UNK', 'Spacecraft clock')
    
    return (AcqMetadata(**meta_data), issues)

def collect_instrument_metadata(telemetry_path: Path, channel: str) -> tuple[InstrumentMetadata, list[Issue]]: 

    issues: list[Issue] = []
    meta_data = {}
    meta_data['CHANNELS'] = HeaderEntry(channel, 'Channels')

    channels = list(channel_to_id.keys())

    # Load telemetry file
    try:
        telemetry_data = json.loads(telemetry_path.read_text(encoding='utf-8'))
        channel_specific_telemetries = {
            channel: telemetry_data.get(channel.upper(), {})
            for channel in channels
        }
    except Exception as e:
        issues.append(
            Issue(
                level="warning",
                message=(f"Failed to read telemetry JSON: {telemetry_path}; "
                         f"Continuing with UNK defaults (reson: {type(e).__name__})"
                        ),
                source=__name__,

            )
        )
        data = InstrumentMetadata(
            CHANNELS= HeaderEntry(channel, 'channels'),
            Vis_TEMP= HeaderEntry('UNK', 'NIR1 detector temperature [DN]'),
            Vis_FPI_TEMP1= HeaderEntry('UNK', 'NIR1 FPI 1 temperature [DN]'),
            Vis_FPI_TEMP2= HeaderEntry('UNK', 'NIR1 FPI 2 temperature [DN]'),
            NIR1_TEMP= HeaderEntry('UNK', 'NIR1 detector temperature [DN]'),
            NIR1_FPI_TEMP1= HeaderEntry('UNK', 'NIR1 FPI 1 temperature [DN]'),
            NIR1_FPI_TEMP2= HeaderEntry('UNK', 'NIR1 FPI 2 temperature [DN]'),
            NIR2_TEMP= HeaderEntry('UNK', 'NIR2 detector temperature [DN]'),
            NIR2_FPI_TEMP1= HeaderEntry('UNK', 'NIR2 FPI 1 temperature [DN]'),
            NIR2_FPI_TEMP2= HeaderEntry('UNK', 'NIR2 FPI 2 temperature [DN]'),
            SWIR_TEMP= HeaderEntry('UNK', 'SWIR detector temperature [DN]'),
            SWIR_FPI_TEMP1= HeaderEntry('UNK', 'SWIR FPI 1 temperature [DN]'),
            SWIR_FPI_TEMP2= HeaderEntry('UNK', 'SWIR FPI 2 temperature [DN]'),
        )
        return (data, issues)

    for ch in channels:
        channel_specific_telemetry = channel_specific_telemetries[ch]
        try: 
            det_temp = channel_specific_telemetry['DET_TEMP']
            meta_data[f'{ch}_CCDTEMP'] = HeaderEntry(str(det_temp), f'{ch} detector temperature [DN]')
        except KeyError as e:
            print('issue happened')
            issues.append(
                Issue(
                    level="warning",
                    message=(f"Missing field in telemetry for {ch}_CCDTEMP; "
                            f"Continuing with UNK defaults (reson: {type(e).__name__})"
                            ),
                    source=__name__,

                )
            )
            meta_data[f'{ch}_CCDTEMP'] = HeaderEntry('UNK', f'{ch} detector temperature [DN]')
        try:
            fpi_temp1 = channel_specific_telemetry['FPI_TEMP1']
            meta_data[f'{ch}_FPI_TEMP1'] = HeaderEntry(str(fpi_temp1), f'{ch} FPI 1 temperature [DN]')
        except KeyError as e:
            issues.append(
                Issue(
                    level="warning",
                    message=(f"Missing field in telemetry for {ch}_FPI_TEMP1; "
                            f"Continuing with UNK defaults (reson: {type(e).__name__})"
                            ),
                    source=__name__,

                )
            )
            meta_data[f'{ch}_FPI_TEMP1'] = HeaderEntry('UNK', f'{channel} FPI 1 temperature [DN]')
        try:
            fpi_temp2 = channel_specific_telemetry['FPI_TEMP2']
            meta_data[f'{ch}_FPI_TEMP2'] = HeaderEntry(str(fpi_temp2), f'{channel} FPI 2 temperature [DN]')
        except KeyError as e:
            issues.append(
                Issue(
                    level="warning",
                    message=(f"Missing field in telemetry for {ch}_FPI_TEMP2; "
                            f"Continuing with UNK defaults (reson: {type(e).__name__})"
                            ),
                    source=__name__,

                )
            )
            meta_data[f'{ch}_FPI_TEMP2'] = HeaderEntry('UNK', f'{channel} FPI 2 temperature [DN]')

    data = InstrumentMetadata(**meta_data)      
    return (data, issues)

def collect_instrument_specific_metadata(config_path: Path, acq_path: Path, channel: str) -> tuple[InstrumentSpecificMetadata, list[Issue]]:

    issues: list[Issue] = []
    meta_data = {}

    frame_count, list_of_frames = list_channel_frames(acq_dir=acq_path, channel=channel)
    frame_numbers = extract_frames(list_of_frames)
    frame_number_string = ','.join(frame_numbers)
    meta_data[f'{channel}_FRAMES'] = HeaderEntry(frame_number_string, 'All frames')

    try: 
        config_data = json.loads(config_path.read_text(encoding='utf-8'))
    except Exception as e:
        issues.append(
                Issue(
                    level="warning",
                    message=(f"Failed to read config.json file;"
                            f"Continuing without instrument specific metadata (reson: {type(e).__name__})"
                            ),
                    source=__name__,

                )
            )
        return (InstrumentSpecificMetadata(fields=meta_data), issues)

    #read SP values for each image
    try:
        match channel:
            case 'Vis': 
                taskFile = config_data['visTaskFile']
            case 'NIR1':
                taskFile = config_data['nir1TaskFile']
            case 'NIR2':
                taskFile = config_data['nir2TaskFile']
            case 'SWIR':
                taskFile = config_data['swirTaskFile']
    except KeyError as e:
        issues.append(
                Issue(
                    level="warning",
                    message=(f"Missing task file entry for channel '{channel}' in config.json'"
                            f"Continuing without instrument specific metadata (reson: {type(e).__name__})"
                            ),
                    source=__name__,

                )
            )
        return (InstrumentSpecificMetadata(fields=meta_data), issues)
    try:
        #Extract sp values from taskValues
        if len(taskFile) % 8 != 0:
            issues.append(Issue(
                level="warning",
                message=f"{channel} taskFile length ({len(taskFile)}) is not divisible by 8. Header data for task values might be corrupted."
            ))
        taskValues = [taskFile[i:i + 8] for i in range(0, len(taskFile), 8)]
        sp_expos_values = [task[1:5] for task in taskValues]
        task_number = len(taskValues)
        meta_data[f'{channel}_TASK_NUMBER'] = HeaderEntry(task_number, 'Number of tasks')
    except Exception as e:
        issues.append(
            Issue(
                level="warning",
                message=(f"Failed to parse task file values;"
                        f"Continuing without instrument specific metadata (reson: {type(e).__name__})"
                        ),
                source=__name__,
            )
        )
        meta_data[f'{channel}_TASK_NUMBER'] = HeaderEntry(frame_count, 'Number of tasks')
        return (InstrumentSpecificMetadata(fields=meta_data), issues)
    if task_number != len(frame_numbers):
        issues.append(
            Issue(
                level="warning",
                message=(f"The number of tasks is different to number of frames;"
                        f"Check config.json tasks for channel: {channel}"
                        ),
                source=__name__,
            )
        )
    if task_number > 3:
        order = check_order(taskValues[3][1], channel)
    elif task_number >= 1:
        order = check_order(taskValues[-1][1], channel)
        issues.append(
            Issue(
                level="info",
                message=(f"Less than 4 acquisitions, the order determined from setpoint index < 3."
                        ),
                source=__name__,
            )
        )
    else:
        issues.append(
            Issue(
                level="warning",
                message=(f"Not enough setpoint values to determine order."
                        ),
                source=__name__,
            )
        )
        order = 'UNK'
    meta_data[f'{channel}_ORDER'] = HeaderEntry(order, "Acquisition order 'LOW / HIGH'.")
    for i, task in enumerate(sp_expos_values):
        n = taskValues[i][0]
        num = f'{n:03d}' # e.g. 1 -> 001
        meta_data[f'{channel}_TASK_{num}'] = HeaderEntry(' '.join(str(x) for x in task), 'SP1 SP2 SP3 ExpDn')

    return (InstrumentSpecificMetadata(fields=meta_data), issues)