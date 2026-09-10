import argparse

from pathlib import Path
from aspect_pipeline.utils.loggin_config import setup_logging
from aspect_pipeline.utils.errors import PipelineError

from aspect_pipeline.main import hello
from aspect_pipeline.orchestrator import run_pipeline
from aspect_pipeline.utils.visualise import visualise_fits_file

def main() -> None:
    """
    Command line interface for ASPECT pipeline.
    Commands:
    - run: runs the pipeline according to the configurations
    - view: visualise a FITS file
    - pds4: generate a PDS4 product according to the configurations
    """

    parser = argparse.ArgumentParser(prog="aspect")
    sub = parser.add_subparsers(dest="cdm", required=True)

    run = sub.add_parser("run", help="Run the pipeline")
    run.add_argument(
        "--config",
        default=None,
        help="Path to YAML configurations. If omitted, searches for configs/example.yaml"
    )


    sub.add_parser("test", help="Run a minimal pipeline test")

    view = sub.add_parser("view", help="Visulise a fits file")
    view.add_argument(
        "--file",
        default=None,
        help="Path to the FITS file to visualise"
    )

    args = parser.parse_args()

    setup_logging('INFO')

    try: 
        if args.cdm == "run":
            config_path = Path(args.config).expanduser() if args.config else None
            run_pipeline(config_path=config_path)
        if args.cdm == "test":
            hello()
        if args.cdm == "view":
            if not args.file:
                print("Missing required argument: --file path/to/file.fits")
            else:
                visualise_fits_file(Path(args.file).expanduser())
    except PipelineError as e:
        raise SystemExit()

if __name__ == "__main__":
    main()