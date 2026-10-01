import argparse

from pathlib import Path
from aspect_pipeline.utils.loggin_config import setup_logging
from aspect_pipeline.utils.errors import PipelineError

from aspect_pipeline.main import hello
from aspect_pipeline.orchestrator import run_pipeline, run_generate_pds4
from aspect_pipeline.utils.visualise import visualise_fits_file, visualise_bin_file
from aspect_pipeline.utils.test_set import make_test_set

def main() -> None:
    """
    Command line interface for ASPECT pipeline.
    Commands:
    - run: runs the pipeline according to the configurations
    - view: visualise a FITS file
    - pds4: generate a PDS4 product according to the configurations
    - make-test-set: generate a synthetic raw/calibration test set
    """

    parser = argparse.ArgumentParser(prog="aspect")
    sub = parser.add_subparsers(dest="cdm", required=True)

    run = sub.add_parser("run", help="Run the pipeline")
    run.add_argument(
        "--config",
        default=None,
        help="Path to YAML configurations. If omitted, searches for configs/example.yaml"
    )

    pds4 = sub.add_parser("pds4", help="Generate PDS4 products")
    pds4.add_argument(
        "--config",
        default=None,
        help="Path to YAML config. If omitted, searches default options"
    )


    sub.add_parser("test", help="Run a minimal pipeline test")

    view = sub.add_parser("view", help="Visualise a fits or bin file")
    view_group = view.add_mutually_exclusive_group(required=True)
    view_group.add_argument(
        "--fits",
        default=None,
        help="Path to the FITS file to visualise"
    )
    view_group.add_argument(
        "--bin",
        default=None,
        help="Path to the .bin file to visualise"
    )

    make_test = sub.add_parser("make-test-set", help="Generate a synthetic raw/calibration test set")
    make_test.add_argument(
        "--input",
        required=True,
        help="Output directory for raw per-channel frames"
    )
    make_test.add_argument(
        "--calibration",
        required=True,
        help="Output directory for calibration files (TEST_DARK/, TEST_FLATS/)"
    )

    args = parser.parse_args()

    setup_logging('INFO')

    try: 
        if args.cdm == "run":
            config_path = Path(args.config).expanduser() if args.config else None
            run_pipeline(config_path=config_path)
        if args.cdm == "pds4":
            config_path = Path(args.config).expanduser() if args.config else None
            run_generate_pds4(config_path=config_path)
        if args.cdm == "test":
            hello()
        if args.cdm == "view":
            if args.fits:
                visualise_fits_file(Path(args.fits).expanduser())
            elif args.bin:
                visualise_bin_file(Path(args.bin).expanduser())
        if args.cdm == "make-test-set":
            make_test_set(Path(args.input).expanduser(), Path(args.calibration).expanduser())
    except PipelineError as e:
        raise SystemExit()

if __name__ == "__main__":
    main()