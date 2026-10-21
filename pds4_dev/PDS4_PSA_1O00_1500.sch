<?xml version="1.0" encoding="UTF-8"?>
  <!-- PDS4 Schematron for Name Space Id:psa  Version:1.5.0.0 - Wed Jul 23 10:57:28 CEST 2025 -->
  <!-- Generated from the PDS4 Information Model Version 1.24.0.0 - System Build 15.1 -->
  <!-- *** This PDS4 schematron file is an operational deliverable. *** -->
<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt2">

  <sch:title>Schematron using XPath 2.0</sch:title>

  <sch:ns uri="http://www.w3.org/2001/XMLSchema-instance" prefix="xsi"/>
  <sch:ns uri="http://pds.nasa.gov/pds4/pds/v1" prefix="pds"/>
  <sch:ns uri="http://psa.esa.int/psa/v1" prefix="psa"/>

		   <!-- ================================================ -->
		   <!-- NOTE:  There are two types of schematron rules.  -->
		   <!--        One type includes rules written for       -->
		   <!--        specific situations. The other type are   -->
		   <!--        generated to validate enumerated value    -->
		   <!--        lists. These two types of rules have been -->
		   <!--        merged together in the rules below.       -->
		   <!-- ================================================ -->
  <sch:pattern>
    <sch:rule context="//pds:File">
      <sch:let name="label_name" value="lower-case(replace(tokenize(document-uri(/), '/')[last()],'\.[^.]+$',''))"/>
      <sch:let name="label_no_vid" value="tokenize($label_name, '__')[1]"/>
      <sch:let name="label_vid" value="tokenize($label_name, '__')[2]"/>
      <sch:let name="data_name" value="lower-case(replace(pds:file_name,'\.[^.]+$',''))"/>
      <sch:let name="data_no_vid" value="tokenize($data_name, '__')[1]"/>
      <sch:let name="data_vid" value="tokenize($data_name, '__')[2]"/>
      <sch:assert test="
                starts-with($data_no_vid, $label_no_vid)
            ">
        <title>//pds:File/Rule</title>
        
                Data filename (<sch:value-of select="$data_no_vid"/>) must have the same stem as the label (<sch:value-of select="$label_no_vid"/>)
            </sch:assert>
      <sch:assert test="
                starts-with($data_vid, $label_vid)
            ">
        <title>//pds:File/Rule</title>
        
                Data filename version ID (<sch:value-of select="$data_vid"/>) must have the same value as the label version ID (<sch:value-of select="$label_vid"/>)
            </sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="//pds:Identification_Area">
      <sch:assert test="
                tokenize(pds:logical_identifier,':')[5]=
                    ('data_raw', 'data_partially_processed', 'calibration_files', 'calibration_raw', 
                    'calibration_partially_processed', 'document', 'geometry', 'context', 'spice_kernels', 'xml_schema')
                or starts-with(tokenize(pds:logical_identifier,':')[5], 'data_calibrated')
                or starts-with(tokenize(pds:logical_identifier,':')[5], 'data_derived')
                or starts-with(tokenize(pds:logical_identifier,':')[5], 'miscellaneous')
                or starts-with(tokenize(pds:logical_identifier,':')[5], 'browse')
            ">
        <title>//pds:Identification_Area/Rule</title>
        The following collections are allowed in the PSA:
    browse[_...]
    data_raw
    data_partially_processed
    data_calibrated[_...]
    data_derived[_...]
    document
    calibration_raw
    calibration_partially_processed
    calibration_files
    geometry
    miscellaneous[_....]
    spice_kernels
    xml_schema</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="//pds:Identification_Area[not(pds:product_class='Product_SPICE_Kernel')]">
      <sch:assert test="pds:Modification_History">
        <title>//pds:Identification_Area[not(pds:product_class='Product_SPICE_Kernel')]/Rule</title>
        Products MUST contain Modification_History</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="//pds:Identification_Area[not(pds:product_class='Product_SPICE_Kernel')]">
      <sch:assert test="pds:version_id = pds:Modification_History/pds:Modification_Detail/pds:version_id">
        <title>//pds:Identification_Area[not(pds:product_class='Product_SPICE_Kernel')]/Rule</title>
        The Modification_History must contain a Modification_Detail entry for the current version_id</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="//pds:Identification_Area[starts-with(tokenize(pds:logical_identifier,':')[5], 'data_')]">
      <sch:assert test="parent::pds:Product_Observational or parent::pds:Product_Collection or parent::pds:Product_Bundle">
        <title>//pds:Identification_Area[starts-with(tokenize(pds:logical_identifier,':')[5], 'data_')]/Rule</title>
        Data collections should contain primarily Product_Observational products (collection and bundle labels are also allowed)</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="//pds:Observation_Area | //pds:Context_Area">
      <sch:assert test="pds:Investigation_Area">
        <title>//pds:Observation_Area | //pds:Context_Area/Rule</title>
        All products MUST contain Investigation_Area in the Observation_Area or Context_Area</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="//pds:Target_Identification">
      <sch:assert test="
                    not(pds:Internal_Reference/pds:lid_reference = (
                    'urn:nasa:pds:context:target:calibrator.stim_lamp',
                    'urn:nasa:pds:context:target:calibrator.test_image',
                    'urn:nasa:pds:context:target:calibrator.plaque',
                    'urn:nasa:pds:context:target:calibrator.responsivity',
                    'urn:nasa:pds:context:target:calibrator.calimg',
                    'urn:nasa:pds:context:target:calibrator.calibration',
                    'urn:nasa:pds:context:target:calibrator.cal_lamps',
                    'urn:nasa:pds:context:target:calibrator.ff_lamp',
                    'urn:nasa:pds:context:target:calibrator.cal'))
            ">
        <title>//pds:Target_Identification/Rule</title>
        
                The following Targets are not allowed in PSA: Test_image, Plaque, Responsivity, CalImage, Calibration, Cal_Lamps, FF_Lamp, Stim_Lamp, Cal
            </sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="//psa:Processing_Inputs/psa:Processing_Input_Identification">
      <sch:assert test="psa:type = (
                'telemetry',
                'PDS product',
                'SPICE kernel',
                'auxiliary')
            ">
        <title>//psa:Processing_Inputs/psa:Processing_Input_Identification/Rule</title>
        The attribute psa:Processing_Input_Identification/psa:type must be equal to one of the following values:
'telemetry','PDS product','SPICE kernel','auxiliary'.
            </sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Browse | /pds:Product_Thumbnail">
      <sch:assert test="
                starts-with(tokenize(pds:Identification_Area/pds:logical_identifier,':')[5], 'browse')
            ">
        <title>/pds:Product_Browse | /pds:Product_Thumbnail/Rule</title>
        Browse or thumbnail products should be in the browse[_...] collection.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Collection">
      <sch:assert test="pds:Context_Area/pds:Investigation_Area[pds:type='Mission']/pds:name">
        <title>/pds:Product_Collection/Rule</title>
        Collection labels must include /pds:Product_Collection/pds:Context_Area/pds:Investigation_Area[pds:type='Mission']/pds:name</sch:assert>
      <sch:assert test="pds:Collection/pds:description">
        <title>/pds:Product_Collection/Rule</title>
        Collection labels must include /pds:Product_Collection/pds:Collection/pds:description</sch:assert>
      <sch:assert test="pds:Context_Area/pds:Observing_System/pds:Observing_System_Component[pds:type='Instrument']/pds:name">
        <title>/pds:Product_Collection/Rule</title>
        Collection labels must include /pds:Product_Collection/pds:Context_Area/pds:Observing_System/pds:Observing_System_Component[pds:type='Instrument']/pds:name</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Document/pds:Identification_Area">
      <sch:assert test="
                tokenize(pds:logical_identifier,':')[5]=('document', 'calibration_files')
            ">
        <title>/pds:Product_Document/pds:Identification_Area/Rule</title>
        Documents (Product_Document) are only allowed in the document or calibration_files collections</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational">
      <sch:let name="filename" value="tokenize(document-uri(/), '/')[last()]"/>
      <sch:assert test="ends-with(tokenize(document-uri(/), '/')[last()], '.lblx')">
        <title>/pds:Product_Observational/Rule</title>
        
Label extension must be .lblx.             
            </sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational/pds:Identification_Area">
      <sch:let name="file-name" value="replace(tokenize(document-uri(/), '/')[last()],'\.[^.]+$','')"/>
      <sch:let name="vid" value="pds:version_id"/>
      <sch:let name="major" value="tokenize(pds:version_id, '\.')[1]"/>
      <sch:let name="minor" value="tokenize(pds:version_id, '\.')[2]"/>
      <sch:let name="vid_filename" value="tokenize($file-name, '__')[last()]"/>
      <sch:assert test="
                $vid_filename = concat($major, '_' , $minor)
            ">
        <title>/pds:Product_Observational/pds:Identification_Area/Rule</title>
        
                Label filename (<sch:value-of select="$file-name"/>) must contain the version ID in the format __[major]_[minor].xml|lblx.
                DEBUG: Currently detected major=<sch:value-of select="$major"/> and minor=<sch:value-of select="$minor"/> in VID <sch:value-of select="$vid"/>
                DEBUG: vid_filename: <sch:value-of select="$vid_filename"/>
            </sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational/pds:Identification_Area[starts-with(tokenize(pds:logical_identifier,':')[5], 'data_derived')]">
      <sch:assert test="parent::*/pds:Observation_Area/pds:Primary_Result_Summary/pds:processing_level='Derived'">
        <title>/pds:Product_Observational/pds:Identification_Area[starts-with(tokenize(pds:logical_identifier,':')[5], 'data_derived')]/Rule</title>
        Products in the data_derived[_*] collections MUST have processing_level=Derived</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational/pds:Identification_Area[tokenize(pds:logical_identifier,':')[5]=
            ('data_raw', 'data_partially_processed', 'data_calibrated', 'calibration_raw', 'calibration_partially_processed')]">
      <sch:assert test="parent::*/pds:Observation_Area/pds:Primary_Result_Summary">
        <title>/pds:Product_Observational/pds:Identification_Area[tokenize(pds:logical_identifier,':')[5]=
            ('data_raw', 'data_partially_processed', 'data_calibrated', 'calibration_raw', 'calibration_partially_processed')]/Rule</title>
        
                Observational products MUST contain Primary_Results_Summary
            </sch:assert>
      <sch:assert test="parent::*/pds:Observation_Area/pds:Primary_Result_Summary/pds:Science_Facets">
        <title>/pds:Product_Observational/pds:Identification_Area[tokenize(pds:logical_identifier,':')[5]=
            ('data_raw', 'data_partially_processed', 'data_calibrated', 'calibration_raw', 'calibration_partially_processed')]/Rule</title>
        
                Observational products MUST contain Primary_Results_Summary/Science_Facets
            </sch:assert>
      <sch:assert test="parent::*/pds:Observation_Area/pds:Observing_System/pds:Observing_System_Component[pds:type eq 'Instrument']">
        <title>/pds:Product_Observational/pds:Identification_Area[tokenize(pds:logical_identifier,':')[5]=
            ('data_raw', 'data_partially_processed', 'data_calibrated', 'calibration_raw', 'calibration_partially_processed')]/Rule</title>
        Each product must have an Observing_System_Component of type Instrument</sch:assert>
      <sch:assert test="parent::*/pds:Observation_Area/pds:Primary_Result_Summary/pds:Science_Facets/pds:wavelength_range">
        <title>/pds:Product_Observational/pds:Identification_Area[tokenize(pds:logical_identifier,':')[5]=
            ('data_raw', 'data_partially_processed', 'data_calibrated', 'calibration_raw', 'calibration_partially_processed')]/Rule</title>
        
                Observational products MUST contain Primary_Results_Summary/Science_Facets/wavelength_range
            </sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational/pds:Identification_Area[tokenize(pds:logical_identifier,':')[5]='data_calibrated']">
      <sch:assert test="parent::*/pds:Observation_Area/pds:Primary_Result_Summary/pds:processing_level='Calibrated'">
        <title>/pds:Product_Observational/pds:Identification_Area[tokenize(pds:logical_identifier,':')[5]='data_calibrated']/Rule</title>
        Products in the data_calibrated collection MUST have processing_level=Calibrated</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational/pds:Identification_Area[tokenize(pds:logical_identifier,':')[5]=('data_partially_processed', 'calibration_partially_processed')]">
      <sch:assert test="parent::*/pds:Observation_Area/pds:Primary_Result_Summary/pds:processing_level='Partially Processed'">
        <title>/pds:Product_Observational/pds:Identification_Area[tokenize(pds:logical_identifier,':')[5]=('data_partially_processed', 'calibration_partially_processed')]/Rule</title>
        Products in the data_partially_processed or calibration_partially_processed collections MUST have processing_level=Partially Processed</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational/pds:Identification_Area[tokenize(pds:logical_identifier,':')[5]=('data_raw', 'calibration_raw')]">
      <sch:assert test="parent::*/pds:Observation_Area/pds:Primary_Result_Summary/pds:processing_level='Raw'">
        <title>/pds:Product_Observational/pds:Identification_Area[tokenize(pds:logical_identifier,':')[5]=('data_raw', 'calibration_raw')]/Rule</title>
        Products in the data_raw or calibration_raw collections MUST have processing_level=Raw</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational/pds:Observation_Area">
      <sch:assert test="pds:Mission_Area">
        <title>/pds:Product_Observational/pds:Observation_Area/Rule</title>
        Observational products MUST contain Mission_Area</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational/pds:Observation_Area/pds:Mission_Area">
      <sch:assert test="psa:Mission_Information">
        <title>/pds:Product_Observational/pds:Observation_Area/pds:Mission_Area/Rule</title>
        Observational products MUST contain psa:Mission_Information</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational/pds:Observation_Area/pds:Mission_Area/psa:Mission_Information">
      <sch:assert test="count(psa:mission_phase_name)=count(psa:mission_phase_identifier)">
        <title>/pds:Product_Observational/pds:Observation_Area/pds:Mission_Area/psa:Mission_Information/Rule</title>
        The number of mission_phase_name and mission_phase_identifier entries must be the same</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational/pds:Observation_Area/pds:Mission_Area/psa:Mission_Information">
      <sch:assert test="psa:mission_phase_identifier or psa:Mission_Phase">
        <title>/pds:Product_Observational/pds:Observation_Area/pds:Mission_Area/psa:Mission_Information/Rule</title>
        Observational products must declare the mission phase using either mission_phase_identifier and mission_phase_name OR the Mission_Phase class</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational/pds:Observation_Area/pds:Observing_System">
      <sch:assert test="pds:Observing_System_Component[pds:type eq 'Host']">
        <title>/pds:Product_Observational/pds:Observation_Area/pds:Observing_System/Rule</title>
        Each product must have an Observing_System_Component of type Host</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational/pds:Observation_Area/pds:Primary_Result_Summary">
      <sch:assert test="pds:processing_level">
        <title>/pds:Product_Observational/pds:Observation_Area/pds:Primary_Result_Summary/Rule</title>
        Observational products MUST contain Primary_Result_Summary/processing_level</sch:assert>
      <sch:assert test="pds:purpose">
        <title>/pds:Product_Observational/pds:Observation_Area/pds:Primary_Result_Summary/Rule</title>
        Observational products MUST contain Primary_Result_Summary/purpose</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational/pds:Observation_Area/pds:Primary_Result_Summary/pds:processing_level">
      <sch:assert test=". != 'Telemetry'">
        <title>/pds:Product_Observational/pds:Observation_Area/pds:Primary_Result_Summary/pds:processing_level/Rule</title>
        
                The PSA does not archive telemetry - data should be unpacked and converted to a suitable format first.
            </sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational/pds:Observation_Area/pds:Target_Identification">
      <sch:assert test="./pds:Internal_Reference/pds:reference_type='data_to_target'">
        <title>/pds:Product_Observational/pds:Observation_Area/pds:Target_Identification/Rule</title>
        Observational products MUST include a lid_reference with type data_to_target in Target_Identification</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational/pds:Reference_List">
      <sch:let name="lidvid_count" value="count(./pds:Source_Product_Internal/pds:lidvid_reference)"/>
      <sch:let name="lidvid_unique_count" value="count(distinct-values(./pds:Source_Product_Internal/pds:lidvid_reference))"/>
      <sch:let name="lid_count" value="count(./pds:Source_Product_Internal/pds:lid_reference)"/>
      <sch:let name="lid_unique_count" value="count(distinct-values(./pds:Source_Product_Internal/pds:lid_reference))"/>
      <sch:assert test="$lidvid_count=$lidvid_unique_count">
        <title>/pds:Product_Observational/pds:Reference_List/Rule</title>
        Source_Product_Internal entries cannot have duplicate LIDVIDs (<sch:value-of select="$lidvid_count"/> entries, but <sch:value-of select="$lidvid_unique_count"/> unique values)</sch:assert>
      <sch:assert test="$lid_count=$lid_unique_count">
        <title>/pds:Product_Observational/pds:Reference_List/Rule</title>
        Source_Product_Internal entries cannot have duplicate LIDs (<sch:value-of select="$lid_count"/> entries, but <sch:value-of select="$lid_unique_count"/> unique values)</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_Observational[
            (pds:Observation_Area/pds:Primary_Result_Summary/pds:processing_level=('Raw', 'Partially Processed', 'Calibrated')) and
            (starts-with(tokenize(pds:Identification_Area/pds:logical_identifier,':')[5], 'data'))]">
      <sch:assert test="tokenize(tokenize(pds:Identification_Area/pds:logical_identifier,':')[6],'_')[2]=('raw','par','cal')">
        <title>/pds:Product_Observational[
            (pds:Observation_Area/pds:Primary_Result_Summary/pds:processing_level=('Raw', 'Partially Processed', 'Calibrated')) and
            (starts-with(tokenize(pds:Identification_Area/pds:logical_identifier,':')[5], 'data'))]/Rule</title>
        PSA observational data products should have the form: {instr}_{level}_{hk|sc}_* - level must be raw, par or cal</sch:assert>
      <sch:assert test="tokenize(tokenize(pds:Identification_Area/pds:logical_identifier,':')[6],'_')[3]=('hk','sc')">
        <title>/pds:Product_Observational[
            (pds:Observation_Area/pds:Primary_Result_Summary/pds:processing_level=('Raw', 'Partially Processed', 'Calibrated')) and
            (starts-with(tokenize(pds:Identification_Area/pds:logical_identifier,':')[5], 'data'))]/Rule</title>
        PSA observational data products should have the form: {instr}_{level}_{hk|sc}_* - hk or sc is required in 3rd place</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="/pds:Product_SPICE_Kernel">
      <sch:assert test="tokenize(pds:Identification_Area/pds:logical_identifier,':')[5] = 'spice_kernels'">
        <title>/pds:Product_SPICE_Kernel/Rule</title>
        Product_SPICE_Kernel can ONLY be in the spice_kernels collection</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="pds:Product_Observational/pds:Identification_Area">
      <sch:let name="file-name" value="replace(tokenize(document-uri(/), '/')[last()],'\.[^.]+$','')"/>
      <sch:let name="file-name-novid" value="tokenize($file-name, '__')[1]"/>
      <sch:let name="lid" value="tokenize(pds:logical_identifier, ':')[last()]"/>
      <sch:assert test="
                lower-case($file-name-novid) = $lid
            ">
        <title>pds:Product_Observational/pds:Identification_Area/Rule</title>
        
                Label filename (<sch:value-of select="$file-name-novid"/>) and last component of the LID (product ID) (<sch:value-of select="$lid"/>) must match for observational products
            </sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="pds:Target_Identification[pds:type eq 'Planet']">
      <sch:assert test="
                starts-with(pds:Internal_Reference/pds:lid_reference,'urn:nasa:pds:context:target:planet.') or
                starts-with(pds:Internal_Reference/pds:lidvid_reference,'urn:nasa:pds:context:target:planet.')
            ">
        <title>pds:Target_Identification[pds:type eq 'Planet']/Rule</title>
        
                If the target is a planet, the LID or LIDVID should start: urn:nasa:pds:context:target:planet.
            </sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="psa:Processing_Input_Identification/psa:type">
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="psa:Sub-Instrument/psa:subtype">
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="psa:Sub-Instrument/psa:type">
      <sch:assert test=". = ('Accelerometer', 'Biology experiment', 'Chemistry laboratory', 'Compilation', 'Dust analyser', 'Electric field instrument', 'Gamma ray detector', 'Gas analyser', 'Gravimeter', 'Imager', 'Imaging spectrometer', 'Interferometer', 'Langmuir probe', 'Magnetometer', 'Mass spectrometer', 'Microphone', 'Microscope', 'Mutual impedance probe', 'Neutron detector', 'Not applicable', 'Particle analyser', 'Polarimeter', 'Radar', 'Radio Receiver', 'Radio science', 'Relaxation sounder', 'SPICE kernels', 'Seismometer', 'Sensor suite', 'Spacecraft sensors', 'Spectrograph', 'Spectrometer', 'Spectrum analyser', 'Sub-surface tool', 'Surface tool', 'Temperature sensor', 'Weather station')">
        <title>psa:Sub-Instrument/psa:type/psa:type</title>
        The attribute psa:Sub-Instrument/psa:type must be equal to one of the following values 'Accelerometer', 'Biology experiment', 'Chemistry laboratory', 'Compilation', 'Dust analyser', 'Electric field instrument', 'Gamma ray detector', 'Gas analyser', 'Gravimeter', 'Imager', 'Imaging spectrometer', 'Interferometer', 'Langmuir probe', 'Magnetometer', 'Mass spectrometer', 'Microphone', 'Microscope', 'Mutual impedance probe', 'Neutron detector', 'Not applicable', 'Particle analyser', 'Polarimeter', 'Radar', 'Radio Receiver', 'Radio science', 'Relaxation sounder', 'SPICE kernels', 'Seismometer', 'Sensor suite', 'Spacecraft sensors', 'Spectrograph', 'Spectrometer', 'Spectrum analyser', 'Sub-surface tool', 'Surface tool', 'Temperature sensor', 'Weather station'.</sch:assert>
    </sch:rule>
  </sch:pattern>
</sch:schema>
