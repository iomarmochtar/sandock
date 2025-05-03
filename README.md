<p align="center">
  <img src="./docs/imgs/logo.jpg" alt="Sandock-Logo" width="40%" />
</p>

<div align="center">
<a href="https://codecov.io/github/iomarmochtar/sandock" > 
 <img src="https://codecov.io/github/iomarmochtar/sandock/graph/badge.svg?token=YEUQ0RQBLW"/> 
 </a>
</div>

<div align="center" >
A <b>docker</b> (or similar) command wrapper to safely execute any program/script in sandboxed environment.
</div>


## 🔥 Motivations / Why you need it

**ps:** this section is optional, you can jump into [Getting Started](#-getting-started) directly if already capture the ideas from simple description above.

### 🛡️ Security Matters

The same concerns as highlighted by the creator of [dangerzone](https://dangerzone.rocks/about/) how a malicious office document can potentially harm/hack your local machine and use container sandboxed env as the solution.

In software or infra engineering the threads cames from a wider factors, these are some samples:

- Typo in dependency name ([Dependency Confusion](https://medium.com/@alex.birsan/dependency-confusion-4a5d60fec610)).
- Malicious library that steal sensitive data ([a news about it](https://thehackernews.com/2025/04/malicious-python-packages-on-pypi.html)).
- Poisoned dependency that affecting commonly used tools (sample: [CVE-2024-3094](https://ubuntu.com/security/CVE-2024-3094)).
- a Crypto exchange loss $18.2 million due to an internal engineering employee executing malicious program ([source](https://voi.id/en/economy/419008)).

`sandock` is not aimed as a silver bullet solution, but at least it can reduce or mitigate some of the potential security issues.

### 🧪 Experiment Without Sweat

Have you ever want to try/install a latest or specific version of an CLI application or programming language but turns out it's makes your local workstation became messed ?

The container approach already solve this and `sandock` comes as the bridge in seemless user experience.


### 🗑️ Isolated and Composible Environment

Reproduceable environment is a hot topic now days and can be achived easly by using container. In software development side there is [devcontainer](https://containers.dev/supporting) with a wide adoption.

`sandock` fill the gap in one lined command execution with a fresh/consistent environment or it can be extended in to isolated user's shell environment.

## ✅ Features

- **Seamless user experience**, execute container program as is been installed in your local workstation, all of the command argument are forwarded to executeable inside container.
- **Program execution shortcuts**, Generate the command shortcuts and with support in defines `aliases` for each executeable inside a container.
- **Auto container dependencies create**, for the custom network, volume and image.
- **Chained/Recursive container build**, by using config `depends_on` in the image declaration.
- **Prevent home dir to be mounted**, as the opposite of [distrobox's behaviour](https://distrobox.it/#security-implications) in share/expose home directory to the container, unless it allowed per program config.
- **Directory configuration**, you can have specific config per folder and it can be excluded by regex patterns.
- **Merged configuration**, if you have main configuration defined with it's `includes` and directory configuration. then all of them will be joined together.
- **Override configuration per program**, at some point you need to change the network type in specific program ?, no need to edit it's config. it will be handled by `--sandbox-arg-*`, and it's adjustable !!.

## 🚀 Getting Started

### 1. Requirements

- Python version >= 3.9 ([the lowest LTS](https://devguide.python.org/versions/#supported-versions) as per this text written).
- Docker installed (or any compactible/drop in, eg: [podman](https://podman.io/), [nerdctl](https://github.com/containerd/nerdctl)).
- [OPTIONAL] [pipx installed](https://github.com/pypa/pipx?tab=readme-ov-file#install-pipx)

### 2. Installation

Basically, `sandock` only use Python's builtins except you will use **yaml** based configuration with it's strong points ([anchor, multiline, commenting, etc](https://yaml.org/spec/1.1/)) that needs to install additional package, just change the package name from `sandock` to `'sandock[yml-config]'`.

> [!INFO]
> we strongly suggest to use [pipx](https://pipx.pypa.io/stable/installation/#installing-pipx) for easier in managing the downloaded executeable.

```bash
pip install sandock
```

Locate where the executeable script has been installed

```
which sandock
```

If you unsure where the executeable is located, run following command to find it.

```bash
pip show sandock | grep "Location: " | awk '{ print $2 }' | sed 's/lib.*$/bin/g'
```

then create a symbolic link to where your env var `$PATH` located.

### 3. Create Configuration File

Initialize configuration file, example:

```bash
cat <<EOF > ~/.sandock.json
{
  "programs": {
    "ruby3.3": {
      "image": "ruby:3.3.8-slim-bookworm",
      "exec": "ruby",
      "aliases": {
        "irb": "/usr/local/bin/irb",
        "bundle": "/usr/local/bin/bundle",
        "gem": "/usr/local/bin/gem",
        "sh": "/bin/bash"
      }
    }
  }
}
EOF
```

See [Configuration section](#️-configuration) for more information about it.

### 4. Configure the shortcuts

> [!INFO]
>
> This step is optional, skip it if not intended to have a program's shortcut

Run `alias` subcommand to generate alias shortcut in executing program, then set in shell profile (asuming zsh) to read it

```bash
sandock alias --expand > ~/.sandock_aliases
echo "source ~/.sandock_aliases" >> ~/.zshrc
```

alternatively, just add following line in your shell profile.

```bash
eval $(sandock alias --expand)
```

**note:** argument `--expand` will include the program's aliases in generated output, from the sample config above you can have shortcut `ruby3.3-bundle` in executing command `bundle` inside container.

### 5. Test it

Create a temporary folder as the place where to run the isolated script.

```bash
mkdir /tmp/test_sandock
cd /tmp/test_sandock
```

create a dummy script

```bash
cat <<EOF > hello.rb
puts "hello world"
puts "from: ruby #{ RUBY_VERSION }p#{ RUBY_PATCHLEVEL }"
puts "current location: #{ File.expand_path(File.dirname(__FILE__)) }"
EOF
```

Then execute

```bash
sandock run ruby3.3 hello.rb
```

or if you create the alias/shortcut in previous step.

```bash
ruby3.3 hello.rb
```

execute it's `sh` alias.

```bash
ruby3.3-sh
```

## ⚙️ Configuration

It's supported **json** and **yaml** based content configuration (as long as the module installed [ref](#2-installation)).
You can find the some of the samples in [examples](./examples/).

### Schema

<details>

<summary>click here to expand</summary>


| Param                                           | Defaults        | Description                                                                                                                                                                                                                                              | Required |
| ----------------------------------------------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| .execution                                      | `{}`            | a section, related to the execution with it's adjustable parameters                                                                                                                                                                                      | `no`     |
| .execution.docker                               | `"docker"`      | container program that will be executed                                                                                                                                                                                                                  | `no`     |
| .execution.container_name_prefix                | `"sandock"`     | the prefix of the created container, if it's not the persistent                                                                                                                                                                                          | `no`     |
| .execution.property_override_prefix_arg         | `"sandbox-arg"` | the prefix of argument name during `run` subcommand that will be overrided some of  program property                                                                                                                                                     | `no`     |
| .execution.alias_program_prefix                 | `""`            | the prefix that will be added in generated alias subcommand                                                                                                                                                                                              | `no`     |
| .config                                         | `{}`            | a section, related to how `sandock` interact with configuration                                                                                                                                                                                          | `no`     |
| .config.current_dir_conf                        | `True`          | enable/disable current directory configuration file ([Dot Config](#dot-config))                                                                                                                                                                          | `no`     |
| .config.current_dir_conf_excludes               | `[]`            | add some folder to be excluded in current directory config reads, you can put a [full match](https://docs.python.org/3/library/re.html#re.fullmatch) regex pattern                                                                                       | `no`     |
| .config.includes                                | `[]`            | load external configuration files, it will be merged into the main configuration for `programs`, `volumes`, `images` and `networks`                                                                                                                      | `no`     |
| .programs                                       | `{}`            | list of programs are defined here                                                                                                                                                                                                                        | `yes`    |
| .programs                                       | `{}`            | list of programs are defined here                                                                                                                                                                                                                        | `yes`    |
| .programs[name].image                           |                 | container image that will be loaded, this also will be set as a reference of image name for the build/custom one                                                                                                                                         | `yes`    |
| .programs[name].exec                            |                 | path of executeable inside container that will be ran as **entrypoint**, this is will be the main one                                                                                                                                                    | `yes`    |
| .programs[name].aliases                         | `{}`            | the maps of any other executeable inside container, during subcommand **alias** by the argument **--generate**, this will generate alias by pattern "[program_name]-[alias]"                                                                             | `no`     |
| .programs[name].interactive                     | `True`          | interactive mode (**-it** ~> keep STDIN and provide pseudo TTY )                                                                                                                                                                                         | `no`     |
| .programs[name].allow_home_dir                  | `False`         | allow ran in (top of) home directory if auto sandbox mount enabled                                                                                                                                                                                       | `no`     |
| .programs[name].name                            |                 | name of created container, if not set then then pattern will be generated is "[execution.container_name_prefix]-[program_name]-[timestamp]"                                                                                                              | `no`     |
| .programs[name].network                         |                 | name of network name that will be used, if it's one of defined in `.networks` then it will be create first (if not exists), you can set with "none" for no network connectivity allowed                                                                  | `no`     |
| .programs[name].hostname                        |                 | container hostname                                                                                                                                                                                                                                       | `no`     |
| .programs[name].build                           | `{}`            | a subsection, define how a container build. the definition is same as defined in section `.images[name]`, if this not defined assuming the image already exists in the local container engine or it will be pulled automatically from container registry | `no`     |
| .programs[name].user                            |                 | a subsection, if set then it will define the user and group id related config in the container side                                                                                                                                                      | `no`     |
| .programs[name].user.uid                        | `0`             | user id in container                                                                                                                                                                                                                                     | `no`     |
| .programs[name].user.gid                        | `0`             | group id in container                                                                                                                                                                                                                                    | `no`     |
| .programs[name].user.keep_id                    | `False`         | set the same uid and gid as the executor/host, this cannot be combined with .uid and .gid                                                                                                                                                                | `no`     |
| .programs[name].workdir                         |                 | set the working directory                                                                                                                                                                                                                                | `no`     |
| .programs[name].platform                        |                 | container platform type, if set, it's also affecting platform type for custom image build                                                                                                                                                                | `no`     |
| .programs[name].persist                         | `{}`            | a subsection, define whether its a temporary container or will be kept exists                                                                                                                                                                            | `no`     |
| .programs[name].persist.enable                  | `False`         | enable/disable persist container                                                                                                                                                                                                                         | `no`     |
| .programs[name].persist.auto_start              | `True`          | enable/disable auto start the container if the status other than **running**                                                                                                                                                                             | `no`     |
| .programs[name].sandbox_mount                   | `{}`            | a subsection, define how the current directory to be (auto) mounted                                                                                                                                                                                      | `no`     |
| .programs[name].sandbox_mount.enable            | `True`          | enable/disable current working directory to be auto mounted                                                                                                                                                                                              | `no`     |
| .programs[name].sandbox_mount.read_only         | `False`         | enable/disable current directory mount as read only mode mounted                                                                                                                                                                                         | `no`     |
| .programs[name].sandbox_mount.current_dir_mount | `"/sandbox"`    | the path of mount point inside container, this also will be set as **--workdir** if the specific configuration was not set                                                                                                                               | `no`     |
| .programs[name].env                             | `{}`            | maps of environment variable that will be injected into container                                                                                                                                                                                        | `no`     |
| .programs[name].volumes                         | `[]`            | list of inline volume mounting definition, `${VOL_DIR}` will dynamically replaced by normalized current path                                                                                                                                             | `no`     |
| .programs[name].ports                           | `[]`            | list of inline port mapping                                                                                                                                                                                                                              | `no`     |
| .programs[name].cap_add                         | `[]`            | list of capabilities that will be added                                                                                                                                                                                                                  | `no`     |
| .programs[name].cap_drop                        | `[]`            | list of capabilities that will be dropped                                                                                                                                                                                                                | `no`     |
| .programs[name].extra_run_args                  | `[]`            | list of argument that will be executed during **run** in container cli, since there are some unique arguments per provider                                                                                                                               | `no`     |
| .programs[name].pre_exec_cmds                   | `[]`            | list of commands that will be execute before running the container                                                                                                                                                                                       | `no`     |
| .volumes                                        | `{}`            | list of volume that will be created by `sandock`, all of volume will have label `created_by.sandock` with value `true`                                                                                                                                   | `no`     |
| .volumes[name].driver                           | `"local"`       | volume driver, ensure it's supported by the container engine                                                                                                                                                                                             | `no`     |
| .volumes[name].driver_opts                      | `{}`            | key-value configuration of driver options                                                                                                                                                                                                                | `no`     |
| .volumes[name].labels                           | `{}`            | key-value label that will be attach to the created volume                                                                                                                                                                                                | `no`     |
| .images                                         | `{}`            | list of container image build definition                                                                                                                                                                                                                 | `no`     |
| .images[name].context                           |                 | path/location during the build time                                                                                                                                                                                                                      | `no`     |

</details>


### Lookup

This defines how `sandock` ordering lookup the main config file, if one condition is met then it will not proceed to next.

1. as explicit mentioned by argument `--config`.
1. the env var by name `SNDK_CFG`.
1. dot config in the home directory `$HOME/.sandock[FORMAT]`, see [Dot Config](#dot-config) for more.
1. dot config in current directory, [Dot Config](#dot-config) for more.
1. 💀 raise an exception for no main configuration can be read.

### Dot Config

dot config configuration file ordered by the format:

1. **.sandock.yml**
1. **.sandock.yaml**
1. **.sandock.json**
1. **.sandock** (the contents will be treat as json formatted)

See how it can be done in variable **CONFIG_FORMAT_DECODER_MAPS** inside [sandbox.config](./sandock/config.py).

## Commands

> [!INFO]
>
> to enable debug mode, you can set argument **--debug** or set env var **SNDK_DEBUG** with value **true** as follow


### run

execute program, all of arguments will be forwarded to the executeable. except for that begins with `--sandbox-arg-*` as the overrides to program's config property ([get list of overrides](#how-to-get-the-list-of-override-arguments-)). special to `--sandbox-arg-exec` it will lookup first by the list of config `.programs[name].aliases`, if it's mapped then the executeable will be followed.

```text
usage: sandock run [-h] program ...

run program

positional arguments:
  program
  program_args  arguments that will be forwarded, excluded for the override args

optional arguments:
  -h, --help    show this help message and exit
```

### list

list all available programs

### alias

create shell (bash, zsh) aliases for each command, use **--expand** for also generates the program

## 🔧 Development

**note:** for better and identical environment, i suggest to use [devcontainer](https://code.visualstudio.com/docs/devcontainers/containers) instead.

### Requirements

- [GNU Make](https://www.gnu.org/software/make/)
- [Poetry](https://python-poetry.org/docs/#installation)

### Dev Dependencies

> [!NOTE]
> Optionally you can create environment variable

Run following command

```sh
poetry install --with=dev
```

### Shortcuts

- `make test`, run unit test.
- `make tidy`, make code tidier using [black](https://github.com/psf/black). you might execute this before running style check linter.
- `make lint`, run style and type check.
- `make test-all`, combine unit test and style+type check.

## 💪🏻 Contributing

Use Github's issue for:

- Bugs reports
- Suggestions
- Confirming for any fix or features to add before create a PR

for PR, please ensure to include the tests based on your code changes.

## ❓ FAQ

### Where the word `sandock` comes from ?

It consist of "sand" for **sandboxing** and "dock" for **docker** as representative of container engine that being used.
in other hand the pronunciation is similar to Indonesian word [Sendok](https://id.wikipedia.org/wiki/Sendok) that means "spoon" where it set as the logo.

### How to make it more "secure" ?

These are what i can suggest:

- use the least privileges on container side (non root user, etc).
- drop all capabilities by default and add some if it's required.
- add security opt [no-new-privileges](https://docs.mirantis.com/mke/3.8/install/plan-deployment/mcr-considerations/no-new-privileges.html).
- disable auto mount sanbox or set it as readonly (**.programs[name].sandbox_mount.read_only**).
- use [gVisor](https://gvisor.dev/) as the container engine.

### How to get the list of override arguments ?

Pass with argument `--sandbox-arg-help` to see all of available one.

> [!NOTE]
> 
> The prefix can be adjusted as config **.execution.property_override_prefix_arg**

### Can it be used in application development ?

Yes, but if it's requires a lot of IDE integrations (auto complete, etc) just use devcontainer instead.

### Why there are 2 kind of configuration format ?

Short answer: **Because it's possible :)**

It was not intended actually, since to create a config object ([dataclass](https://docs.python.org/3/library/dataclasses.html)) is as simple as provide the `dict` that will be mapped automatically to it's properties. means you can extend it to another parser (eg: [toml](https://pypi.org/project/tomli/)).

But i just want make it as an optional as possible, so the bare minimum one is that cames as the builtin (json).
