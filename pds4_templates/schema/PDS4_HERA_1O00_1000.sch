<?xml version="1.0" encoding="UTF-8"?>
  <!-- PDS4 Schematron for Name Space Id:hera  Version:1.0.0.0 - Mon Oct 19 16:28:50 CEST 2026 -->
  <!-- Generated from the PDS4 Information Model Version 1.24.0.0 - System Build 15.1 -->
  <!-- *** This PDS4 schematron file is an operational deliverable. *** -->
<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt2">

  <sch:title>Schematron using XPath 2.0</sch:title>

  <sch:ns uri="http://www.w3.org/2001/XMLSchema-instance" prefix="xsi"/>
  <sch:ns uri="http://pds.nasa.gov/pds4/pds/v1" prefix="pds"/>
  <sch:ns uri="http://pds.nasa.gov/pds4/mission/hera/v1" prefix="hera"/>

		   <!-- ================================================ -->
		   <!-- NOTE:  There are two types of schematron rules.  -->
		   <!--        One type includes rules written for       -->
		   <!--        specific situations. The other type are   -->
		   <!--        generated to validate enumerated value    -->
		   <!--        lists. These two types of rules have been -->
		   <!--        merged together in the rules below.       -->
		   <!-- ================================================ -->
  <sch:pattern>
    <sch:rule context="//pds:Mission_Area">
      <sch:assert test="hera:Spacecraft_Status">
        <title>//pds:Mission_Area/Rule</title>
        
                hera:Spacecraft_Status is required within Mission_Area for Hera mission products.
            </sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="hera:Spacecraft_Status/hera:juventas_mission_phase">
      <sch:assert test=". = ('Phase 1', 'Phase 2', 'Stowed')">
        <title>hera:Spacecraft_Status/hera:juventas_mission_phase/hera:juventas_mission_phase</title>
        The attribute hera:Spacecraft_Status/hera:juventas_mission_phase must be equal to one of the following values 'Phase 1', 'Phase 2', 'Stowed'.</sch:assert>
    </sch:rule>
  </sch:pattern>
  <sch:pattern>
    <sch:rule context="hera:Spacecraft_Status/hera:milani_mission_phase">
      <sch:assert test=". = ('Phase 1', 'Phase 2', 'Stowed')">
        <title>hera:Spacecraft_Status/hera:milani_mission_phase/hera:milani_mission_phase</title>
        The attribute hera:Spacecraft_Status/hera:milani_mission_phase must be equal to one of the following values 'Phase 1', 'Phase 2', 'Stowed'.</sch:assert>
    </sch:rule>
  </sch:pattern>
</sch:schema>
