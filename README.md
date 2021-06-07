<!--
*** Thanks for checking out this README Template. If you have a suggestion that would
*** make this better, please fork the repo and create a pull request or simply open
*** an issue with the tag "enhancement".
*** Thanks again! Now go create something AMAZING! :D
-->





<!-- PROJECT SHIELDS -->
<!--
*** I'm using markdown "reference style" links for readability.
*** Reference links are enclosed in brackets [ ] instead of parentheses ( ).
*** See the bottom of this document for the declaration of the reference variables
*** for contributors-url, forks-url, etc. This is an optional, concise syntax you may use.
*** https://www.markdownguide.org/basic-syntax/#reference-style-links
-->
[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]
[![LinkedIn][linkedin-shield]][linkedin-url]



<!-- PROJECT LOGO -->
<br />
<p align="center">
  <a href="https://github.com/orcunbaslak/solarian-datalogger">
    <img src="https://github.com/orcunbaslak/solarian-datalogger/blob/master/images/solarian_logo.png?raw=true" alt="Logo" width="411" height="162">
  </a>

  <h3 align="center">Solarian Datalogger</h3>

  <p align="center">
    Solarian datalogger is a datalogger for solar systems. You can write a driver for your device
    and call the driver using the YAML file provided. You should implement a get_data() method
    to correctly read all data and return a JSON file. 
    <br />
    <br />
    <a href="https://github.com/orcunbaslak/solarian-datalogger/issues">Report Bug</a>
    ·
    <a href="https://github.com/orcunbaslak/solarian-datalogger/issues">Request Feature</a>
  </p>
</p>



<!-- TABLE OF CONTENTS -->
## Table of Contents

* [About the Project](#about-the-project)
  * [Built With](#built-with)
* [Getting Started](#getting-started)
  * [Prerequisites](#prerequisites)
  * [Installation](#installation)
* [Usage](#usage)
* [Roadmap](#roadmap)
* [Contributing](#contributing)
* [License](#license)
* [Similar Projects](#similar-projects)
* [Contact](#contact)



<!-- ABOUT THE PROJECT -->
## About The Project

There are many causes for people to write code. As an engineering company owner; I was frusturated to see how incompetent datalogging companies
doing business around. Data losses, buggy software and other issues led me to write a minimalist piece of software for solar system just to get the
basic data from inverters/sensors/string combiners into our influxdb server.

Here's why:
* As engineers; our time is money. Bad data makes us invest more time in it. We don't want to fix someone else's errors.
* Good data yields good engineering analysis and accurate results. You deserve more **precise** and **accurate** results.
* Why consume the time trying to fix someone elses inaccurate data instead of enjoying the sun outside with your family?

Please feel free to fork or send pull requests. Please keep the code as minimal as possible.

### Built With
This project has been coded with Python 3. Modbus-tk library has been chosen for device communication. Paho MQTT is choosen for MQTT communication
* [Python](https://www.python.org/)
* [modbus-tk](https://github.com/ljean/modbus-tk)
* [PyYAML](https://github.com/yaml/pyyaml)
* [Paho MQTT](https://github.com/eclipse/paho.mqtt.python)


<!-- GETTING STARTED -->
## Getting Started

Follow the steps below to prepare the environment for the project.

### Prerequisites

First you need to get Python 3 installed and running with dependencies correctly installed.
* bash
```sh
sudo apt update
sudo apt-get -y dist-upgrade
sudo apt-get -y install git python3-distutils gcc python3-dev parallel lftp
sudo curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
sudo python3 get-pip.py
sudo pip3 install pyyaml modbus_tk psutil paho-mqtt graypy
```

### Installation

1. Clone the repo (Change the directory if you want)
```sh
git clone https://github.com/orcunbaslak/solarian-datalogger /home/pi/solarian-datalogger
```
2. Create a configuration file from the sample
```sh
cd config
cp sample-config.yml config.yml
```
3. Edit the configuration file `config.yml`
```sh
nano config.yml
```
4. Create a MQTT file from the sample (OPTIONAL)
```sh
cp sample-mqtt.yml mqtt.yml
```
5. Edit the configuration file `mqtt.yml` (OPTIONAL)
```sh
nano mqtt.yml
```
6. Create a GrayLog file from the sample (OPTIONAL)
```sh
cp sample-graylog.yml graylog.yml
```
7. Edit the configuration file `graylog.yml` (OPTIONAL)
```sh
nano graylog.yml
```


<!-- USAGE EXAMPLES -->
## Usage

You can feed the file to Python3 interpreter and it's all good to go given you've prepared a correct YAML file and 
network/serial connections are working as intended.

```sh
python3 datalogger.py
```

You can use specific args to modify inner workings of the script
```sh
  --config CONFIG   YAML file containing device settings. Default "config.yml"
  --log LOG         Log levels, DEBUG, INFO, WARNING, ERROR or CRITICAL
  --pi-analytics    Enable or disable RaspberryPi device data acquisition
  --verbose         Print the acquired data to console
  --write-disabled  Disables file writing. Dry-run.
  --mqtt            Enables the MQTT feature. Mqtt config file must be set.
  --graylog         Pushes logging data to the specified GrayLog server. Graylog config file must be set.
```

<!-- ROADMAP -->
## Roadmap

See the [open issues](https://github.com/orcunbaslak/solarian-datalogger/issues) for a list of proposed features (and known issues).



<!-- CONTRIBUTING -->
## Contributing

Contributions are what make the open source community such an amazing place to be learn, inspire, and create. Any contributions you make are **greatly appreciated**.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/NewInverter`)
3. Commit your Changes (`git commit -m 'Add a new inverter driver'`)
4. Push to the Branch (`git push origin feature/NewInverter`)
5. Open a Pull Request



<!-- LICENSE -->
## License

Distributed under the GNU GPL v3 License. See `LICENSE` for more information.

<!-- SIMILAR PROJECTS -->
## Similar Projects

You can find a list of similar projects that I used for help and inspiration.

* [Solariot](https://github.com/meltaxa/solariot)
* [Modbus-logger](https://github.com/GuillermoElectrico/modbus-logger)
* [PVStats](https://github.com/ptarcher/pvstats)
* [Modbus4MQTT](https://github.com/tjhowse/modbus4mqtt)
* [Energy-Meter-Logger](https://github.com/samuelphy/energy-meter-logger)


<!-- CONTACT -->
## Contact

Orçun Başlak - [@orcunbaslak](https://twitter.com/orcunbaslak) - [website](https://orcun.baslak.com/) - orcun.baslak@solarian.com.tr

Solarian Enerji - [@solarianenerji](https://twitter.com/solarianenerji) - [website](https://www.solarian.com.tr/en/) - info@solarian.com.tr

Project Link: [https://github.com/orcunbaslak/solarian-datalogger](https://github.com/orcunbaslak/solarian-datalogger)


<!-- MARKDOWN LINKS & IMAGES -->
<!-- https://www.markdownguide.org/basic-syntax/#reference-style-links -->
[contributors-shield]: https://img.shields.io/github/contributors/orcunbaslak/solarian-datalogger.svg?style=flat-square
[contributors-url]: https://github.com/orcunbaslak/solarian-datalogger/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/orcunbaslak/solarian-dataloggere.svg?style=flat-square
[forks-url]: https://github.com/orcunbaslak/solarian-datalogger/network/members
[stars-shield]: https://img.shields.io/github/stars/orcunbaslak/solarian-datalogger.svg?style=flat-square
[stars-url]: https://github.com/orcunbaslak/solarian-datalogger/stargazers
[issues-shield]: https://img.shields.io/github/issues/orcunbaslak/solarian-datalogger.svg?style=flat-square
[issues-url]: https://github.com/orcunbaslak/solarian-datalogger/issues
[license-shield]: https://img.shields.io/github/license/orcunbaslak/solarian-datalogger.svg?style=flat-square
[license-url]: https://github.com/orcunbaslak/solarian-datalogger/blob/master/LICENSE
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=flat-square&logo=linkedin&colorB=555
[linkedin-url]: https://linkedin.com/in/orcunbaslak