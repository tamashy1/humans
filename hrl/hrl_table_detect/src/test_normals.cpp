#include <numeric>
#include <ros/ros.h>
#include "sensor_msgs/PointCloud2.h"
#include <pcl/features/normal_3d.h>
#include <pcl/kdtree/kdtree_flann.h>
#include "pcl/point_types.h"
#include <pcl_ros/point_cloud.h>
#include <pcl/point_cloud.h>
#include <pcl/features/principal_curvatures.h>

#include <tf/transform_listener.h>
#include "pcl_ros/transforms.h"
#include <boost/make_shared.hpp>
#include <boost/thread/mutex.hpp>
#include <cv_bridge/cv_bridge.h>
#include <opencv/cv.h>
#include <opencv2/imgproc/imgproc.hpp>
#include <opencv2/highgui/highgui.hpp>
#include <image_transport/image_transport.h>
#include <sensor_msgs/image_encodings.h>
#include <geometry_msgs/PoseArray.h>
#include <hrl_table_detect/DetectTableStart.h>
#include <hrl_table_detect/DetectTableStop.h>
#include <hrl_table_detect/DetectTableInst.h>
#include <LinearMath/btMatrix3x3.h>
#include <LinearMath/btQuaternion.h>
#include <hrl_cvblobslib/Blob.h>
#include <hrl_cvblobslib/BlobResult.h>

using namespace sensor_msgs;
using namespace std;
namespace enc = sensor_msgs::image_encodings;
namespace hrl_table_detect {

class TestNormals {
    public:
        ros::Subscriber pc_sub;
        ros::NodeHandle nh;
        ros::Publisher pc_pub, pc_pub2;
        tf::TransformListener tf_listener;

        TestNormals();
        void onInit();
        void pcCallback(sensor_msgs::PointCloud2::ConstPtr pc_msg);
};

    TestNormals::TestNormals() {
    }

    void TestNormals::onInit() {
        pc_pub = nh.advertise<pcl::PointCloud<pcl::PointXYZRGB> >("/normal_vis", 1);
        pc_pub2 = nh.advertise<pcl::PointCloud<pcl::PointXYZRGB> >("/normal_vis2", 1);
        pc_sub = nh.subscribe("/kinect_head/rgb/points", 1, &TestNormals::pcCallback, this);
        ros::Duration(1.0).sleep();
    }

    void TestNormals::pcCallback(sensor_msgs::PointCloud2::ConstPtr pc_msg) {
        pcl::PointCloud<pcl::PointXYZRGB> pc_full, pc_full_frame;
        pcl::fromROSMsg(*pc_msg, pc_full);
        string base_frame("/base_link");
        ros::Time now = ros::Time::now();
        
        tf_listener.waitForTransform(pc_msg->header.frame_id, base_frame, now, ros::Duration(3.0));
        pcl_ros::transformPointCloud(base_frame, pc_full, pc_full_frame, tf_listener);
        pcl::PointCloud<pcl::PointXYZRGB>::ConstPtr pc_full_frame_ptr = boost::make_shared<pcl::PointCloud<pcl::PointXYZRGB> >(pc_full_frame);
        // pc_full_frame is in torso lift frame

        pcl::KdTree<pcl::PointXYZRGB>::Ptr normals_tree = boost::make_shared<pcl::KdTreeFLANN<pcl::PointXYZRGB> > ();
        pcl::NormalEstimation<pcl::PointXYZRGB, pcl::Normal> n3d;
        n3d.setKSearch(15);
        n3d.setSearchMethod(normals_tree);
        n3d.setInputCloud(pc_full_frame_ptr);
        pcl::PointCloud<pcl::Normal> cloud_normals;
        n3d.compute(cloud_normals);
        pcl::PrincipalCurvaturesEstimation<pcl::PointXYZRGB, pcl::Normal, pcl::PrincipalCurvatures> pce;
        pce.setKSearch(15);
        pce.setSearchMethod(normals_tree);
        pce.setInputCloud(pc_full_frame_ptr);
        pcl::PointCloud<pcl::PrincipalCurvatures> princip_curves;
        pcl::PointCloud<pcl::Normal>::ConstPtr cloud_normals_ptr = boost::make_shared<pcl::PointCloud<pcl::Normal> >(cloud_normals);
        pce.setInputNormals(cloud_normals_ptr);
        pce.compute(princip_curves);
        pcl::PointCloud<pcl::PointXYZRGB> cloud_normals_colors, princip_curves_colors;

        int i=0;
        BOOST_FOREACH(const pcl::Normal& pt, cloud_normals.points) {
            i++;
            if(pt.normal[0] != pt.normal[0] || pt.normal[1] != pt.normal[1] || pt.normal[2] != pt.normal[2])
                continue;
            pcl::PointXYZRGB cur_pt = pc_full_frame.at(i-1, 0);
            double ang = fabs((acos(pt.normal[2]) - CV_PI/2)/CV_PI*2);
            //cout << ang << " ";
            double thresh = 0.5;

            if(ang > thresh)
                ((uint32_t*) &cur_pt.rgb)[0] = ((uint32_t) ((ang-thresh)/(CV_PI/2)*256))<<16 | 0xFF000000;
            else
                ((uint32_t*) &cur_pt.rgb)[0] = ((uint32_t) ((thresh-ang)/thresh*256)) | 0xFF000000;
            
            cloud_normals_colors.push_back(cur_pt);

            pcl::PointXYZRGB p_cur_pt = pc_full_frame.at(i-1, 0);
            pcl::PrincipalCurvatures pcurves = princip_curves.at(i-1, 0);
            //cout << pcurves << " ";
            if(pcurves.pc1 < 0.8)
                ((uint32_t*) &p_cur_pt.rgb)[0] = 0xFF0000FF;
            else if(pcurves.pc2 > 0.0001)
                ((uint32_t*) &p_cur_pt.rgb)[0] = ((uint32_t) (min(fabs((double)pcurves.pc1/pcurves.pc2), 30.0)/30.0*256))<<16 | 0xFF000000;
            else
                ((uint32_t*) &p_cur_pt.rgb)[0] = (256)<<16 | 0xFF00FF00;
            princip_curves_colors.push_back(p_cur_pt);
        }
        cloud_normals_colors.header.stamp = ros::Time::now();
        cloud_normals_colors.header.frame_id = base_frame;
        pc_pub.publish(cloud_normals_colors);

        princip_curves_colors.header.stamp = ros::Time::now();
        princip_curves_colors.header.frame_id = base_frame;
        pc_pub2.publish(princip_curves_colors);

    }
};

using namespace hrl_table_detect;

int main(int argc, char **argv)
{
    ros::init(argc, argv, "test_normals");
    TestNormals ta;
    ta.onInit();
    ros::spin();
    return 0;
}



