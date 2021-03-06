Cooperative transport with iRobot Create 2.
===
Ros node implementation.

Prerequisites
---
* [irobotcreate2](https://github.com/MirkoFerrati/irobotcreate2ros.git)
* [math3d](https://pypi.python.org/pypi/math3d/3.0.0)
* [ompl](http://ompl.kavrakilab.org/download.html)
* [sympy.mpmath](http://docs.sympy.org/0.7.6/modules/mpmath/index.html)

Instructions
---
Just clone the repository in the src folder of a catkin workspace. Then run catkin_make.

If you wish to start a simulation you need to copy the stock gazebo worlds, i.e., *.world.original,
inside /worlds.

Usage
---
To launch the simulation with three robots type:
```
roslaunch cooperative_transport simulation.launch
```
The launch file runs gazebo, the main controller (for each simulated robot) and a node that simulates the ir light bumper sensors of the irobot using the Hokuyo laser range finder data provided by gazebo.

The ir readings are available in the topics /ir_bumper_x where x identifies the robot.

