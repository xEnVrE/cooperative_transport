import rospy
import smach
import numpy as np
from subscriber import Subscriber
from planner import Planner, RectangularObstacle, CircularObstacle
from control.point_to_point import PointToPoint
from control.proportional_control import proportional_control
from smach import StateMachine, Iterator
from cooperative_transport.msg import TaskState
from threading import Lock

def construct_sm(controller_index, robots_state, irbumper, boxstate, set_control):
    """Construct the top level state machine for cooperative transport.

    Arguments:
    controller_index (int): index of the robot
    robots_state (Subscriber[]): list of Subscribers to robots odometry
    irbumper (Subscriber): Subscriber to this robot ir bumper
    boxstate (Subscriber): Subscriber to the box state estimation
    set_control (function): function that publish a twist
    """
    sm = StateMachine(outcomes=['transport_ok', 'transport_failed'])

    with sm:    
    ##############################################################################################
    # TOP LEVEL STATE MACHINE
    ##############################################################################################
    #
        box_attachment = StateMachine(outcomes=['attachment_ok', 'attachment_failed'])
        box_attachment.userdata.path = []

        with box_attachment:
        ##########################################################################################
        # BOX ATTACHMENT STATE MACHINE
        ##########################################################################################
        #
            box_approach = Iterator(outcomes=['approach_ok'],\
                                    input_keys=['path'],\
                                    output_keys=[],\
                                    it=box_attachment.userdata.path,\
                                    it_label='goal',\
                                    exhausted_outcome='approach_ok')

            with box_approach:
            ######################################################################################
            # BOX APPROACH ITERATOR
            ######################################################################################
            #
                box_approach_container = StateMachine(outcomes=['approach_continue'])
                with box_approach_container:
                ###################################################################################
                # BOX APPROACH CONTAINER
                ###################################################################################
                #
                    alignment = Alignment(robots_state[controller_index], set_control)
                    StateMachine.add('ALIGNMENT',\
                                     alignment,\
                                     transitions={'alignment_ok':'GO_TO_POINT'})

                    go_to_point = GoToPoint(robots_state[controller_index], set_control)
                    StateMachine.add('GO_TO_POINT',\
                                     go_to_point,\
                                     transitions={'point_reached':'approach_continue'})

                #
                ###################################################################################
                
                Iterator.set_contained_state('CONTAINER_STATE', 
                                             box_approach_container, 
                                             loop_outcomes=['approach_continue'])

            #
            ######################################################################################

            wait_for_turn = WaitForTurn(controller_index)
            StateMachine.add('WAIT_FOR_TURN',\
                             wait_for_turn,\
                             transitions={'my_turn':'PLAN_TRAJECTORY'})

            plan_trajectory = PlanTrajectory(controller_index, robots_state, boxstate)
            StateMachine.add('PLAN_TRAJECTORY', plan_trajectory,\
                             transitions={'path_found':'BOX_APPROACH',\
                                          'plan_failed':'attachment_failed'},
                             remapping={'path':'path'})

            StateMachine.add('BOX_APPROACH',\
                             box_approach,\
                             transitions={'approach_ok':'BOX_FINE_APPROACH'})
        #
        ##########################################################################################

        StateMachine.add('BOX_ATTACHMENT', box_attachment,\
                         transitions={'attachment_failed':'transport_failed',\
                                      'attachment_ok':'MOVE_BOX'})
    #
    ##############################################################################################
            
    return sm
        
class WaitForTurn(smach.State):
    """State of the fsm in which the robot waits its turn to approach the box.

    Outcomes:
    my_turn : time for the robot to approach the box

    Inputs: 
    none
    
    Outputs: 
    none
    """
    def __init__(self, controller_index):
        """Initialize the state of the fsm.

        Arguments:
        controller_index (int): index of the robot
        """
        smach.State.__init__(self, outcomes=['my_turn'])
        
        self.controller_index = controller_index

        # Subscribe and publish to the topic 'task_state'
        # Robots use this topic to wait for their turn to approach to the box

        self.turn_state_pub = rospy.Publisher('task_state', TaskState, queue_size=50)
        self.turn_state_sub = rospy.Subscriber('task_state', TaskState, self.callback)
        self.turn__state = []

        # Lock used to protect the variable turn_state
        self.lock = Lock()

        # State clock
        self.clock = rospy.Rate(1)

    def callback(data):
        """Update the turn_state variable.

        Arguments:
        data (TaskState): last task state received by the node.
        """
        self.lock.acquire()
        # Add robot_id to the turn_state list for every new robot
        if not data.robot_id in self.task_state:
            self.task_state.append(data.robot_id)
        self.lock.release()
        
    def turn_number(self):
        """Return the number of robots in the turn_state list."""
        self.lock.acquire()
        number = len(self.task_state)
        self.lock.release()

        return number
        
    def execute(self, userdata):
        """Execute the main activity of the fsm state.

        Arguments:
        userdata: inputs and outputs of the fsm state."""
        # Wait for turn
        while self.turn_number != self.controller_index:
            self.clock.sleep()

        return 'my_turn'

class PlanTrajectory(smach.State):
    """State of the fsm in which the robot find its path to the box.

    Outcomes:
    path_found: a path was found
    plan_failed: the planning failed
    
    Inputs:
    none

    Outputs:
    path: the path found by the planning algorithm
    """
    def __init__(self, controller_index, robots_state, boxstate):
        """Initialize the state of the fsm.

        Arguments:
        controller_index (int): index of the robot
        robots_state (Subscriber[]): list of Subscribers to robots odometry
        boxstate (Subscriber): Subscriber to box state
        """
        smach.State.__init__(self, outcomes=['path_found','plan_failed'], output_keys=['path'])
        
        self.controller_index = controller_index
        self.robots_state = robots_state
        self.boxstate = boxstate

    def execute(self, userdata):

        # Initialize the planner
        lower_bound = rospy.get_param('planner_lower_bound')
        upper_bound = rospy.get_param('planner_upper_bound')
        self.planner = Planner(lower_bound, upper_bound)

        # Add obstacles for the neighbor robots
        robot_radius = rospy.get_param('robot_radius')
        for robot_index,robot_state in enumerate(self.robots_state):
            if robot_index != self.controller_index:

                x_robot = robot_state.data.pose.pose.position.x
                y_robot = robot_state.data.pose.pose.position.y
                obstacle = CircularObstacle(robot_radius, x_robot, y_robot , robot_radius)

                self.planner.add_obstacle(CircularObstacle())
            
        # Add obstacle for the box
        box_parameters = rospy.get_param('box')
        length = box_parameters['length']
        width = box_parameters['width']
        x_box = self.box_state.data.x
        y_box = self.box_state.data.y
        theta_box = self.box_state.data.theta
        obstacle = RectangularObstacle(length, width, x_box, y_box, theta_box)
        self.planner.add_obstacle(obstacle)

        # TODO:
        
class Alignment(smach.State):
    """State of the fsm in which the robot rotates in order to align
    itself with the line of sight between its center and the next goal.
    
    Outcomes:
    alignment_ok: the robot rotated successfully

    Inputs:
    goal (float[]): the goal position
    
    Outputs:
    none
    """
    def __init__(self, robot_state, set_control):
        """Initialize the state of the fsm.

        Arguments:
        robots_state (Subscriber[]): list of Subscribers to robots odometry
        set_control (function): function that publish a twist
        """
        smach.State.__init__(self, outcomes=['alignment_ok'], input_keys=['goal'])

        self.robot_state = robot_state
        self.set_control = set_control

        self.max_angular_v = float(rospy.get_param('max_angular_v'))
        self.kp = 10
        
        # State clock
        self.clock = rospy.Rate(100)
        
    def execute(self, userdata):
        # Read the sensors
        x = self.robot_state.data.pose.pose.position.x
        y = self.robot_state.data.pose.pose.position.y
        theta = utils.quaternion_to_yaw(self.robot_state.data.pose.pose.orientation)

        # Parameter of control
        reference_input = np.arctan2(userdata.goal[1] - y, userdata.goal[0] - x)  
        error = reference_input - theta
        tolerance = 0.1

        while error > tolerance:
            # Read the sensors
            theta = utils.quaternion_to_yaw(self.robot_state.data.pose.pose.orientation)

            # Evaluate the control
            angular_v = proportional_control(self.kp, reference_input, theta, self.max_angular_v)
            angular_v *= -1 # Gazebo Bug
            
            # Set the control
            self.set_control(0, angular_v)

            self.clock.sleep()
        
        return 'alignment_ok'
        
class GoToPoint(smach.State):
    """State of the fsm in which the robot moves to a precise location.

    Outcomes:
    point_reached: the robot moved successfully
    
    Inputs:
    goal (float[]): the goal position

    Outputs:
    none
    """
    def __init__(self, robot_state, set_control):
        """Initialize the state of the fsm.

        Arguments:
        robots_state (Subscriber[]): list of Subscribers to robots odometry
        set_control (function): function that publish a twist
        """
        smach.State.__init__(self, outcomes=['point_reached'], input_keys=['goal'])
        
        self.robot_state = robot_state
        self.set_control = set_control

        # Initialize the point2point controller
        self.max_forward_v = float(rospy.get_param('max_forward_v'))
        self.max_angular_v = float(rospy.get_param('max_angular_v'))
        self.controller = PointToPoint(self.max_forward_v, self.max_angular_v)

        # State clock
        self.clock = rospy.Rate(100)

    def execute(self, userdata):
        """Execute the main activity of the fsm state.

        Arguments:
        userdata: inputs and outputs of the fsm state."""
        # Set the goal point
        self.controller.goal_point(userdata.goal)

        # Move the robot to the goal point
        done = False
        while not done:
            # Read the sensors
            x = self.robot_state.data.pose.pose.position.x
            y = self.robot_state.data.pose.pose.position.y
            theta = utils.quaternion_to_yaw(self.robot_state.data.pose.pose.orientation)
            forward_v = self.robot_state.data.twist.twist.linear.x

            # Evaluate the control
            done, forward_v, angular_v = self.controller.control_law([x, y, theta], forward_v)
            angular_v *= -1 # Gazebo Bug

            # Set the control
            self.set_control(forward_v, angular_v)

            self.clock.sleep()

        return 'point_reached'

