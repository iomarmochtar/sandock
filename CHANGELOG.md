# Change Log

## [0.7.0]

### Features and Enhancements

- [cli] adjustable container executor per program
- [cli] support custom sandbox executor class for extendable parameters
- [config] add default custom executor for `apple_container`
- [config] set volume type as optional
- [config] fetch another and merge another property by using `fetch_prop(location)`
- [config] toggleable `fetch_prop(location)` by env `SNDK_FETCH_PROP` (value `yes`)
- [config] flatten if the container caller is array and the result of `fetch_prop(location)` helper is an array
- [packaging] actual version will be injected during build and publish pipeline

## [0.6.0]

### Features and Enhancements

- [cli] introduce `--sandbox-arg-recreate-img` to rebuild container image 


## [0.5.0]

### Features and Enhancements

- [cli] add overrides for container ports publishing
- [dev] migrate gnu-make to go-task

## [0.4.0]

### Features and Enhancements

- [img] escape home directory alias for `dockerFile` and `context`

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