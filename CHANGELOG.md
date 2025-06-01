# Change Log

## [0.3.0]

### Features and Enhancements

- [config] add option in custom image build to dump it (default: off)
- [img] save custom image as archive file if dump option enabled
- [img] automatically remove the previous dumped image (default: on)


## [0.2.0]

### Features and Enhancements

- Volume backup (encrypted and compressed) by using [restic](https://restic.net/) (container)
- Multiple extendable configuration for `program`, `volume`, `image` and `network` using key `extends`

### Bug Fixes

- Commit hash not shown in version information

## [0.1.0]

### Features and Enhancements

- Initial release